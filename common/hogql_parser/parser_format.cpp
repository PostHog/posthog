// parser_format.cpp - HogQL pretty-printer
//
// Phase-1 formatter. Walks the ANTLR parse tree of a `select` rule and emits a
// re-indented, keyword-uppercased representation of the same query. Designed
// to be cheap to call (single tree walk, no AST allocation) and safe to fall
// back from: the WASM entry point catches every parser error and signals "no
// format" to the caller, which then leaves the user's text alone.
//
// Approach:
//   - Structural rules (selectStmt, fromClause, joinExpr, where/group/having
//     /order/limit clauses, CTEs, subqueries, set ops) are formatted by hand
//     so we control where line breaks and indents land.
//   - Everything below those clauses (column expressions, literals, calls,
//     identifiers, operators) is emitted by `emit_subtree_tokens`, a shared
//     token walker that applies a small spacing table. This is what keeps the
//     code from blowing up to one visitor method per columnExpr alternative.
//   - Hog program statements and HogQLX tag elements are emitted verbatim
//     from the source slice — no attempt to format them.

#include <cctype>
#include <sstream>
#include <string>
#include <vector>

#include "HogQLLexer.h"
#include "HogQLParser.h"

#include "json.h"

using namespace std;
using namespace antlr4;

namespace {

constexpr int INDENT_WIDTH = 4;
// When a SELECT list has more than this many items, break it one-per-line.
constexpr size_t COLUMN_BREAK_THRESHOLD = 3;

// True if `t` is a SQL keyword token (i.e. an explicit reserved word in the
// grammar). The lexer assigns these the lowest token type values, so a single
// numeric range covers them. Anything at or after IDENTIFIER is a literal,
// identifier, operator, or punctuation.
bool isKeywordToken(int t) {
    return t >= HogQLLexer::ALL && t < HogQLLexer::IDENTIFIER;
}

bool isOpenBracket(int t) {
    return t == HogQLLexer::LPAREN || t == HogQLLexer::LBRACKET || t == HogQLLexer::LBRACE;
}

bool isCloseBracket(int t) {
    return t == HogQLLexer::RPAREN || t == HogQLLexer::RBRACKET || t == HogQLLexer::RBRACE;
}

// Tokens that hug their right neighbour (no space after them).
bool noSpaceAfter(int t) {
    if (isOpenBracket(t)) return true;
    switch (t) {
        case HogQLLexer::DOT:
        case HogQLLexer::DOUBLECOLON:
        case HogQLLexer::COLON:
        case HogQLLexer::HASH:
        case HogQLLexer::DOLLAR:
        case HogQLLexer::NULL_PROPERTY:  // "?."
            return true;
        default:
            return false;
    }
}

// Tokens that hug their left neighbour (no space before them).
bool noSpaceBefore(int t) {
    if (isCloseBracket(t)) return true;
    switch (t) {
        case HogQLLexer::COMMA:
        case HogQLLexer::SEMICOLON:
        case HogQLLexer::DOT:
        case HogQLLexer::DOUBLECOLON:
        case HogQLLexer::COLON:
        case HogQLLexer::NULL_PROPERTY:
            return true;
        default:
            return false;
    }
}

// NB: distinguishing unary `-1` from binary `a - 1` purely by adjacent token
// types is unsafe — both produce a DASH followed by a numeric literal in the
// token stream, but only the binary form needs surrounding spaces. v1 plays
// it safe and always spaces around `-`/`+`; the trade-off is `-1` rendering
// as `- 1`, which is uglier but never wrong.

string toUpperCopy(const string& s) {
    string out;
    out.reserve(s.size());
    for (char c : s) out.push_back(static_cast<char>(toupper(static_cast<unsigned char>(c))));
    return out;
}

}  // namespace

class HogQLFormatter {
   public:
    explicit HogQLFormatter(const string& source) : source_(source) {}

    string formatSelect(HogQLParser::SelectContext* ctx) {
        out_.str("");
        indent_ = 0;
        last_emitted_token_ = -1;
        at_line_start_ = true;
        formatSelectRule(ctx);
        return out_.str();
    }

   private:
    const string& source_;
    ostringstream out_;
    int indent_ = 0;
    int last_emitted_token_ = -1;
    bool at_line_start_ = true;

    // ---- low-level emit primitives --------------------------------------

    string indentSpaces() const { return string(static_cast<size_t>(indent_) * INDENT_WIDTH, ' '); }

    void newline() {
        out_ << '\n' << indentSpaces();
        at_line_start_ = true;
        last_emitted_token_ = -1;
    }

    // Emit a single token's text, applying the spacing table against the
    // previously emitted token. Keywords get uppercased; everything else
    // (identifiers, literals, operators, punctuation) is passed through.
    void emitToken(Token* tok) {
        if (!tok || tok->getType() == Token::EOF) return;
        int type = tok->getType();
        string text = tok->getText();
        if (isKeywordToken(type) || type == HogQLLexer::NULL_SQL || type == HogQLLexer::INF ||
            type == HogQLLexer::NAN_SQL) {
            text = toUpperCopy(text);
        }

        if (!at_line_start_ && last_emitted_token_ != -1) {
            bool needsSpace = !(noSpaceAfter(last_emitted_token_) || noSpaceBefore(type));
            if (needsSpace) out_ << ' ';
        }

        out_ << text;
        at_line_start_ = false;
        last_emitted_token_ = type;
    }

    // Emit a literal keyword (uppercased), as if it were a token of "word"
    // class. Used when we want to inject e.g. "SELECT" without going through a
    // TerminalNode — keeps spacing consistent.
    void emitKeyword(const string& kw) {
        if (!at_line_start_ && last_emitted_token_ != -1 && !noSpaceAfter(last_emitted_token_)) {
            out_ << ' ';
        }
        out_ << toUpperCopy(kw);
        at_line_start_ = false;
        // Pretend we just emitted a generic word token so the next emitToken
        // call inserts a space if appropriate.
        last_emitted_token_ = HogQLLexer::IDENTIFIER;
    }

    // Walk every terminal token under `tree` in source order and emit it
    // through `emitToken`. The default fallback for expression subtrees we
    // don't want to format structurally.
    void emitSubtreeTokens(tree::ParseTree* tree) {
        if (!tree) return;
        if (auto* term = dynamic_cast<tree::TerminalNode*>(tree)) {
            emitToken(term->getSymbol());
            return;
        }
        for (auto* child : tree->children) {
            emitSubtreeTokens(child);
        }
    }

    // Emit the source slice between the start and stop tokens of `ctx`,
    // verbatim. Used for Hog program statements and HogQLX tag elements where
    // we don't want to risk reformatting at all.
    void emitVerbatim(ParserRuleContext* ctx) {
        if (!ctx) return;
        auto* start = ctx->getStart();
        auto* stop = ctx->getStop();
        if (!start || !stop) return;
        size_t startIdx = start->getStartIndex();
        size_t stopIdx = stop->getStopIndex();
        if (startIdx == string::npos || stopIdx == string::npos || stopIdx < startIdx) return;
        if (stopIdx >= source_.size()) stopIdx = source_.size() - 1;
        string slice = source_.substr(startIdx, stopIdx - startIdx + 1);

        if (!at_line_start_ && last_emitted_token_ != -1) out_ << ' ';
        out_ << slice;
        at_line_start_ = false;
        // Treat as a generic word so subsequent emits space correctly.
        last_emitted_token_ = HogQLLexer::IDENTIFIER;
    }

    // ---- structural formatters ------------------------------------------

    void formatSelectRule(HogQLParser::SelectContext* ctx) {
        if (auto* set = ctx->selectSetStmt()) {
            formatSelectSetStmt(set);
        } else if (auto* stmt = ctx->selectStmt()) {
            formatSelectStmt(stmt);
        } else if (auto* tag = ctx->hogqlxTagElement()) {
            // Out of scope for structural formatting — emit as-is.
            emitVerbatim(tag);
        }
        // The trailing optional SEMICOLON is intentionally dropped here: this
        // entry point formats exactly one statement, and the JS caller owns
        // statement separators (it splits a multi-statement document, formats
        // each piece, and rejoins them with `;`).
    }

    void formatSelectSetStmt(HogQLParser::SelectSetStmtContext* ctx) {
        formatSelectStmtWithParens(ctx->selectStmtWithParens());
        for (auto* sub : ctx->subsequentSelectSetClause()) {
            newline();
            formatSubsequentSelectSetClause(sub);
        }
        if (auto* order = ctx->orderByClause()) {
            newline();
            formatOrderByClause(order);
        }
        if (auto* limit = ctx->limitAndOffsetClauseOptional()) {
            newline();
            formatLimitAndOffsetClauseOptional(limit);
        }
    }

    void formatSubsequentSelectSetClause(HogQLParser::SubsequentSelectSetClauseContext* ctx) {
        // The set-op keywords (UNION, INTERSECT, EXCEPT, ALL, DISTINCT, BY,
        // NAME) are direct terminal children of this context, in order, before
        // the nested selectStmtWithParens. Walk children and emit set-op
        // keywords as a single line, then handle the parenthesized stmt.
        for (auto* child : ctx->children) {
            if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                emitToken(term->getSymbol());
            } else if (auto* paren = dynamic_cast<HogQLParser::SelectStmtWithParensContext*>(child)) {
                newline();
                formatSelectStmtWithParens(paren);
            }
        }
    }

    void formatSelectStmtWithParens(HogQLParser::SelectStmtWithParensContext* ctx) {
        // Cases: bare selectStmt, withClause LPAREN selectSetStmt RPAREN,
        // LPAREN selectSetStmt RPAREN, or placeholder.
        if (auto* stmt = ctx->selectStmt()) {
            formatSelectStmt(stmt);
            return;
        }
        if (auto* placeholder = ctx->placeholder()) {
            emitSubtreeTokens(placeholder);
            return;
        }
        // Parenthesized selectSetStmt, optionally with a leading WITH clause.
        bool emittedWith = false;
        if (auto* withCtx = ctx->withClause()) {
            formatWithClause(withCtx);
            emittedWith = true;
        }
        if (auto* set = ctx->selectSetStmt()) {
            if (emittedWith) newline();
            emitKeyword("(");
            // "(" tokens are open brackets; ensure no trailing space.
            last_emitted_token_ = HogQLLexer::LPAREN;
            indent_++;
            newline();
            formatSelectSetStmt(set);
            indent_--;
            newline();
            // Close paren as a bare token so spacing rules apply.
            out_ << ')';
            at_line_start_ = false;
            last_emitted_token_ = HogQLLexer::RPAREN;
        }
    }

    void formatSelectStmt(HogQLParser::SelectStmtContext* ctx) {
        if (auto* withCtx = ctx->withClause()) {
            formatWithClause(withCtx);
            newline();
        }

        emitKeyword("SELECT");
        if (ctx->DISTINCT()) emitKeyword("DISTINCT");
        if (auto* top = ctx->topClause()) {
            // "TOP n" / "TOP n WITH TIES" — small enough to emit inline.
            for (auto* child : top->children) emitSubtreeTokens(child);
        }

        // SELECT list — break one-per-line when many columns.
        formatSelectColumnList(ctx->selectColumnExprListBeforeFrom());

        if (auto* from = ctx->fromClause()) {
            newline();
            formatFromClause(from);
        }
        if (auto* aj = ctx->arrayJoinClause()) {
            newline();
            // "[LEFT|INNER] ARRAY JOIN <list>" — emit inline.
            emitSubtreeTokens(aj);
        }
        if (auto* prew = ctx->prewhereClause()) {
            newline();
            emitKeyword("PREWHERE");
            indent_++;
            newline();
            emitSubtreeTokens(prew->columnExpr());
            indent_--;
        }
        if (auto* where = ctx->whereClause()) {
            newline();
            emitKeyword("WHERE");
            indent_++;
            newline();
            emitSubtreeTokens(where->columnExpr());
            indent_--;
        }
        // sampleClause may appear before or after whereClause depending on
        // USING placement; keep it inline at its natural position by walking
        // the remaining clause children in order would be ideal, but the
        // grammar already exposes typed accessors. Emit any sampleClause(s):
        for (auto* sc : ctx->sampleClause()) {
            newline();
            emitSubtreeTokens(sc);
        }
        if (auto* group = ctx->groupByClause()) {
            newline();
            formatGroupByClause(group);
        }
        // WITH (CUBE | ROLLUP) and WITH TOTALS modifiers between GROUP BY and
        // HAVING are intentionally not handled in v1 — they require token-level
        // discrimination from the WITH that introduces a CTE.
        if (auto* having = ctx->havingClause()) {
            newline();
            emitKeyword("HAVING");
            indent_++;
            newline();
            emitSubtreeTokens(having->columnExpr());
            indent_--;
        }
        if (auto* qual = ctx->qualifyClause()) {
            newline();
            emitKeyword("QUALIFY");
            indent_++;
            newline();
            emitSubtreeTokens(qual->columnExpr());
            indent_--;
        }
        if (auto* win = ctx->windowClause()) {
            newline();
            emitSubtreeTokens(win);
        }
        if (auto* order = ctx->orderByClause()) {
            newline();
            formatOrderByClause(order);
        }
        if (auto* limitBy = ctx->limitByClause()) {
            newline();
            emitSubtreeTokens(limitBy);
        }
        if (auto* limit = ctx->limitAndOffsetClause()) {
            newline();
            emitSubtreeTokens(limit);
        }
        if (auto* off = ctx->offsetOnlyClause()) {
            newline();
            emitSubtreeTokens(off);
        }
        if (auto* settings = ctx->settingsClause()) {
            newline();
            emitSubtreeTokens(settings);
        }
    }

    // SELECT list — break one column per line if more than COLUMN_BREAK_THRESHOLD
    // top-level columns. Otherwise emit inline.
    void formatSelectColumnList(HogQLParser::SelectColumnExprListBeforeFromContext* ctx) {
        if (!ctx) return;

        vector<HogQLParser::SelectColumnExprContext*> cols;
        // Both alternatives (TrailingComma / Plain) wrap a selectColumnExprList
        // or a sequence of selectColumnExpr children — collect them.
        for (auto* child : ctx->children) {
            if (auto* col = dynamic_cast<HogQLParser::SelectColumnExprContext*>(child)) {
                cols.push_back(col);
            } else if (auto* list = dynamic_cast<HogQLParser::SelectColumnExprListContext*>(child)) {
                for (auto* sub : list->selectColumnExpr()) cols.push_back(sub);
            }
        }

        bool breakLines = cols.size() > COLUMN_BREAK_THRESHOLD;
        indent_++;
        for (size_t i = 0; i < cols.size(); i++) {
            if (i == 0) {
                if (breakLines) {
                    newline();
                } else {
                    // single space after SELECT
                }
            } else {
                if (breakLines) {
                    out_ << ',';
                    last_emitted_token_ = HogQLLexer::COMMA;
                    newline();
                } else {
                    out_ << ',';
                    last_emitted_token_ = HogQLLexer::COMMA;
                }
            }
            emitSubtreeTokens(cols[i]);
        }
        indent_--;
    }

    void formatWithClause(HogQLParser::WithClauseContext* ctx) {
        emitKeyword("WITH");
        if (ctx->RECURSIVE()) emitKeyword("RECURSIVE");
        auto* list = ctx->withExprList();
        if (!list) return;
        auto exprs = list->withExpr();
        bool breakLines = exprs.size() > 1;
        indent_++;
        for (size_t i = 0; i < exprs.size(); i++) {
            if (i == 0) {
                if (breakLines) newline();
            } else {
                out_ << ',';
                last_emitted_token_ = HogQLLexer::COMMA;
                newline();
            }
            formatWithExpr(exprs[i]);
        }
        indent_--;
    }

    void formatWithExpr(HogQLParser::WithExprContext* ctx) {
        if (auto* sub = dynamic_cast<HogQLParser::WithExprSubqueryContext*>(ctx)) {
            // identifier withExprColumnNameList? (USING KEY ...)? AS (NOT? MATERIALIZED)? LPAREN selectSetStmt RPAREN
            // Simpler: emit everything before the inner LPAREN as tokens, then
            // structurally format the inner selectSetStmt.
            auto* setStmt = sub->selectSetStmt();
            if (!setStmt) {
                emitSubtreeTokens(sub);
                return;
            }
            for (auto* child : sub->children) {
                if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                    emitToken(term->getSymbol());
                    if (term->getSymbol()->getType() == HogQLLexer::LPAREN) {
                        indent_++;
                        newline();
                        formatSelectSetStmt(setStmt);
                        indent_--;
                        newline();
                    }
                } else if (auto* set = dynamic_cast<HogQLParser::SelectSetStmtContext*>(child)) {
                    // already emitted above, skip
                    (void)set;
                } else {
                    // identifier / withExprColumnNameList — emit verbatim
                    emitSubtreeTokens(child);
                }
            }
        } else {
            // WithExprColumn: columnExpr AS identifier — single line is fine.
            emitSubtreeTokens(ctx);
        }
    }

    void formatFromClause(HogQLParser::FromClauseContext* ctx) {
        emitKeyword("FROM");
        indent_++;
        newline();
        formatJoinExpr(ctx->joinExpr());
        indent_--;
    }

    // Emit a join chain. Each JOIN appears on its own line at the same indent
    // as the FROM target; the ON / USING constraint is indented one further.
    void formatJoinExpr(HogQLParser::JoinExprContext* ctx) {
        if (!ctx) return;

        if (auto* parens = dynamic_cast<HogQLParser::JoinExprParensContext*>(ctx)) {
            out_ << '(';
            last_emitted_token_ = HogQLLexer::LPAREN;
            at_line_start_ = false;
            indent_++;
            newline();
            formatJoinExpr(parens->joinExpr());
            indent_--;
            newline();
            out_ << ')';
            last_emitted_token_ = HogQLLexer::RPAREN;
            return;
        }

        if (auto* op = dynamic_cast<HogQLParser::JoinExprOpContext*>(ctx)) {
            // joinExpr NATURAL? joinOp? JOIN joinExpr joinConstraintClause?
            auto joins = op->joinExpr();
            formatJoinExpr(joins[0]);
            newline();
            // Emit NATURAL? joinOp? JOIN as inline tokens. The left joinExpr
            // is the first child and is already formatted; once we hit the
            // right-hand joinExpr we stop. joinConstraintClause is handled
            // separately below.
            bool seenLeft = false;
            for (auto* child : op->children) {
                if (dynamic_cast<HogQLParser::JoinExprContext*>(child)) {
                    if (!seenLeft) {
                        seenLeft = true;
                        continue;
                    }
                    break;
                }
                if (dynamic_cast<HogQLParser::JoinConstraintClauseContext*>(child)) {
                    break;
                }
                if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                    emitToken(term->getSymbol());
                } else if (dynamic_cast<HogQLParser::JoinOpContext*>(child)) {
                    emitSubtreeTokens(child);
                }
            }
            // Right-hand side, slightly indented.
            indent_++;
            newline();
            formatJoinExpr(joins[1]);
            indent_--;
            if (auto* constraint = op->joinConstraintClause()) {
                indent_++;
                newline();
                emitSubtreeTokens(constraint);
                indent_--;
            }
            return;
        }

        if (auto* pos = dynamic_cast<HogQLParser::JoinExprPositionalContext*>(ctx)) {
            auto joins = pos->joinExpr();
            formatJoinExpr(joins[0]);
            newline();
            emitKeyword("POSITIONAL");
            emitKeyword("JOIN");
            indent_++;
            newline();
            formatJoinExpr(joins[1]);
            indent_--;
            if (auto* constraint = pos->joinConstraintClause()) {
                indent_++;
                newline();
                emitSubtreeTokens(constraint);
                indent_--;
            }
            return;
        }

        if (auto* cross = dynamic_cast<HogQLParser::JoinExprCrossOpContext*>(ctx)) {
            auto joins = cross->joinExpr();
            formatJoinExpr(joins[0]);
            newline();
            emitSubtreeTokens(cross->joinOpCross());
            indent_++;
            newline();
            formatJoinExpr(joins[1]);
            indent_--;
            return;
        }

        if (auto* table = dynamic_cast<HogQLParser::JoinExprTableContext*>(ctx)) {
            // tableExpr FINAL? sampleClause?
            formatTableExpr(table->tableExpr());
            if (table->FINAL()) emitKeyword("FINAL");
            if (auto* sc = table->sampleClause()) emitSubtreeTokens(sc);
            return;
        }

        if (dynamic_cast<HogQLParser::JoinExprPivotContext*>(ctx) ||
            dynamic_cast<HogQLParser::JoinExprUnpivotContext*>(ctx)) {
            // PIVOT / UNPIVOT chains — emit inline as tokens. Rare enough that
            // structural formatting isn't worth the complexity for v1.
            emitSubtreeTokens(ctx);
            return;
        }

        emitSubtreeTokens(ctx);
    }

    void formatTableExpr(HogQLParser::TableExprContext* ctx) {
        if (!ctx) return;
        if (auto* sub = dynamic_cast<HogQLParser::TableExprSubqueryContext*>(ctx)) {
            out_ << '(';
            last_emitted_token_ = HogQLLexer::LPAREN;
            at_line_start_ = false;
            indent_++;
            newline();
            formatSelectSetStmt(sub->selectSetStmt());
            indent_--;
            newline();
            out_ << ')';
            last_emitted_token_ = HogQLLexer::RPAREN;
            return;
        }
        if (auto* alias = dynamic_cast<HogQLParser::TableExprAliasContext*>(ctx)) {
            formatTableExpr(alias->tableExpr());
            // Then alias parts (alias | AS identifier) columnAliases?
            for (auto* child : alias->children) {
                if (child == alias->tableExpr()) continue;
                emitSubtreeTokens(child);
            }
            return;
        }
        emitSubtreeTokens(ctx);
    }

    void formatGroupByClause(HogQLParser::GroupByClauseContext* ctx) {
        emitKeyword("GROUP");
        emitKeyword("BY");
        // The grammar has many shapes here (ALL, CUBE/ROLLUP(list), GROUPING SETS,
        // or a plain columnExprList). Emit the non-GROUP/non-BY children inline
        // with a one-level indent.
        indent_++;
        newline();
        bool sawHead = false;
        for (auto* child : ctx->children) {
            if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                int t = term->getSymbol()->getType();
                if ((t == HogQLLexer::GROUP || t == HogQLLexer::BY) && !sawHead) continue;
                sawHead = true;
                emitToken(term->getSymbol());
            } else {
                sawHead = true;
                emitSubtreeTokens(child);
            }
        }
        indent_--;
    }

    void formatOrderByClause(HogQLParser::OrderByClauseContext* ctx) {
        emitKeyword("ORDER");
        emitKeyword("BY");
        auto* list = ctx->orderExprList();
        if (!list) return;
        auto exprs = list->orderExpr();
        bool breakLines = exprs.size() > COLUMN_BREAK_THRESHOLD;
        indent_++;
        for (size_t i = 0; i < exprs.size(); i++) {
            if (i == 0) {
                if (breakLines) newline();
            } else {
                out_ << ',';
                last_emitted_token_ = HogQLLexer::COMMA;
                if (breakLines) newline();
            }
            emitSubtreeTokens(exprs[i]);
        }
        if (auto* interp = ctx->interpolateClause()) emitSubtreeTokens(interp);
        indent_--;
    }

    void formatLimitAndOffsetClauseOptional(HogQLParser::LimitAndOffsetClauseOptionalContext* ctx) {
        emitSubtreeTokens(ctx);
    }
};

// Top-level entry: parse + format. Returns a JSON string of either:
//   {"ok": true,  "output": "<formatted>"}
//   {"ok": false, "error": "<message>"}
// The error path is intentionally generic — the WASM caller doesn't need to
// distinguish syntax errors from anything else; it just falls back.
string format_hogql_select(const string& input) {
    try {
        ANTLRInputStream stream(input.c_str(), input.length());
        HogQLLexer lexer(&stream);
        CommonTokenStream tokens(&lexer);
        HogQLParser parser(&tokens);

        // Capture lexer & parser errors instead of letting ANTLR write to
        // stderr. Any error short-circuits to the "not well-formed" path.
        struct CollectErrors : public BaseErrorListener {
            bool sawError = false;
            void syntaxError(Recognizer*, Token*, size_t, size_t, const string&,
                             exception_ptr) override {
                sawError = true;
            }
        } listener;
        lexer.removeErrorListeners();
        lexer.addErrorListener(&listener);
        parser.removeErrorListeners();
        parser.addErrorListener(&listener);

        auto* tree = parser.select();
        if (listener.sawError || !tree) {
            Json err = Json::object();
            err["ok"] = false;
            err["error"] = "syntax error";
            return err.dump();
        }

        HogQLFormatter formatter(input);
        string formatted = formatter.formatSelect(tree);

        Json ok = Json::object();
        ok["ok"] = true;
        ok["output"] = formatted;
        return ok.dump();
    } catch (...) {
        Json err = Json::object();
        err["ok"] = false;
        err["error"] = "internal formatter error";
        return err.dump();
    }
}
