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
//   - Comments live on the lexer's hidden channel, invisible to the parser
//     tree. A single pre-pass (`attachComments`) walks the token stream and
//     attaches each comment to a default-channel source token as either
//     leading or trailing; the formatter then drains those during emission.

#include <cctype>
#include <sstream>
#include <string>
#include <unordered_map>
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

// Collect every direct-child COMMA TerminalNode under `node`. Used by the
// per-clause formatters to thread source commas (and their attached
// comments) through `emitToken`.
void collectCommaTerminals(tree::ParseTree* node, vector<tree::TerminalNode*>& out) {
    for (auto* child : node->children) {
        if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
            if (term->getSymbol()->getType() == HogQLLexer::COMMA) out.push_back(term);
        }
    }
}

// Whether `t` is a comment token (either `--` or `/* */`). Comments share the
// hidden lexer channel with whitespace, so a channel check alone isn't enough.
bool isCommentToken(Token* t) {
    int type = t->getType();
    return type == HogQLLexer::SINGLE_LINE_COMMENT || type == HogQLLexer::MULTI_LINE_COMMENT;
}

bool isLineComment(Token* t) { return t->getType() == HogQLLexer::SINGLE_LINE_COMMENT; }

// Comments attached to a default-channel token by `attachComments`. Leading
// comments are emitted just before the token; trailing comments just after.
struct AttachedComments {
    vector<Token*> leading;
    vector<Token*> trailing;
};

// Walk every token in the stream and decide where each comment should attach.
// (`BufferedTokenStream::getHiddenTokensToLeft/Right` could be invoked lazily
// per default-channel token instead; the bulk pre-pass is chosen for one-shot
// deterministic assignment and to make the leading-vs-trailing rule live in
// one place rather than scattered through every emit call site.)
//
// The rule is intentionally simple — Prettier-class heuristics aren't worth
// it for SQL, where comments mostly sit between clauses, after a clause, or
// inline mid-expression:
//
//   - Comment on the same source line as the previous default-channel token
//     → trailing of that token. ("SELECT a -- foo")
//   - Otherwise → leading of the next default-channel token. (The comment
//     lives on its own line and describes what comes next.)
//   - If there is no next visible default-channel token (we're past the body
//     of the SELECT and only `;` / EOF remain — neither of which the formatter
//     emits) → trailing of the previous default-channel token instead, so the
//     comment doesn't fall on the floor.
//
// SEMICOLON and EOF are deliberately skipped when searching for the "next
// default-channel token", because the formatter never emits them and so any
// leading-of-SEMICOLON attachment would never fire.
unordered_map<size_t, AttachedComments> attachComments(CommonTokenStream* tokens) {
    unordered_map<size_t, AttachedComments> map;
    if (!tokens) return map;
    tokens->fill();

    size_t n = tokens->size();
    size_t prev_default = SIZE_MAX;

    auto isFormatterVisible = [](Token* t) {
        if (t->getChannel() != Token::DEFAULT_CHANNEL) return false;
        int type = t->getType();
        return type != Token::EOF && type != HogQLLexer::SEMICOLON;
    };

    for (size_t i = 0; i < n; i++) {
        Token* t = tokens->get(i);
        if (t->getChannel() == Token::DEFAULT_CHANNEL) {
            if (isFormatterVisible(t)) prev_default = i;
            continue;
        }
        if (!isCommentToken(t)) continue;  // whitespace, skip

        Token* prev = (prev_default != SIZE_MAX) ? tokens->get(prev_default) : nullptr;
        bool sameLineAsPrev = prev && t->getLine() == prev->getLine();

        if (sameLineAsPrev) {
            map[prev_default].trailing.push_back(t);
            continue;
        }

        size_t next_default = SIZE_MAX;
        for (size_t j = i + 1; j < n; j++) {
            if (isFormatterVisible(tokens->get(j))) {
                next_default = j;
                break;
            }
        }

        if (next_default != SIZE_MAX) {
            map[next_default].leading.push_back(t);
        } else if (prev_default != SIZE_MAX) {
            map[prev_default].trailing.push_back(t);
        }
        // else: comment with no surrounding default-channel tokens. Should be
        // impossible for a well-formed select — drop it.
    }
    return map;
}

}  // namespace

class HogQLFormatter {
   public:
    HogQLFormatter(const string& source, CommonTokenStream* tokens)
        : source_(source), comments_(attachComments(tokens)) {}

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
    unordered_map<size_t, AttachedComments> comments_;
    ostringstream out_;
    int indent_ = 0;
    int last_emitted_token_ = -1;
    // True while the cursor is at column 0 with no content yet on the current
    // line. Indent is written lazily on the next real emission via
    // `flushIndent()`. Two effects that come from this: consecutive
    // `newline()` calls collapse, and trailing `--` comments (whose own text
    // already terminates in `\n`) don't produce blank+indented lines.
    bool at_line_start_ = true;

    // ---- low-level emit primitives --------------------------------------

    string indentSpaces() const { return string(static_cast<size_t>(indent_) * INDENT_WIDTH, ' '); }

    void newline() {
        if (at_line_start_) return;
        out_ << '\n';
        at_line_start_ = true;
        last_emitted_token_ = -1;
    }

    void flushIndent() {
        if (!at_line_start_) return;
        out_ << indentSpaces();
        at_line_start_ = false;
    }

    // Emit a literal character at the current indent and pretend the lexer
    // produced a `tokenType` token. Used for synthesizing punctuation
    // (`,`, `(`, `)`) when there isn't a corresponding source TerminalNode.
    void emitRaw(char c, int tokenType) {
        flushIndent();
        out_ << c;
        last_emitted_token_ = tokenType;
        at_line_start_ = false;
    }

    // Emit a single token's text, applying the spacing table against the
    // previously emitted token. Keywords get uppercased; everything else
    // (identifiers, literals, operators, punctuation) is passed through.
    // Also drains any leading/trailing comments attached to this token by
    // `attachComments`.
    void emitToken(Token* tok) {
        if (!tok || tok->getType() == Token::EOF) return;
        emitLeadingCommentsFor(tok);

        int type = tok->getType();
        string text = tok->getText();
        if (isKeywordToken(type) || type == HogQLLexer::NULL_SQL || type == HogQLLexer::INF ||
            type == HogQLLexer::NAN_SQL) {
            text = toUpperCopy(text);
        }

        if (at_line_start_) {
            flushIndent();
        } else if (last_emitted_token_ != -1) {
            bool needsSpace = !(noSpaceAfter(last_emitted_token_) || noSpaceBefore(type));
            if (needsSpace) out_ << ' ';
        }

        out_ << text;
        at_line_start_ = false;
        last_emitted_token_ = type;

        emitTrailingCommentsFor(tok);
    }

    // Comment helpers -----------------------------------------------------

    void emitLeadingCommentsFor(Token* anchor) {
        if (comments_.empty()) return;
        auto it = comments_.find(anchor->getTokenIndex());
        if (it == comments_.end()) return;
        for (Token* c : it->second.leading) {
            emitLeadingComment(c, anchor);
        }
    }

    void emitTrailingCommentsFor(Token* tok) {
        if (comments_.empty()) return;
        auto it = comments_.find(tok->getTokenIndex());
        if (it == comments_.end()) return;
        for (Token* c : it->second.trailing) {
            emitTrailingComment(c);
        }
    }

    // A block comment on the same source line as its anchor token stays
    // inline ahead of it (`/* hint */ id`). Anything else gets its own line
    // at the current indent. Line comments can never be inline-leading —
    // `-- foo` runs to end-of-line by definition, so it would push the
    // anchor down anyway.
    void emitLeadingComment(Token* c, Token* anchor) {
        bool inlineBlock = !isLineComment(c) && anchor && c->getLine() == anchor->getLine();
        if (inlineBlock) {
            if (at_line_start_) {
                flushIndent();
            } else if (last_emitted_token_ != -1 && !noSpaceAfter(last_emitted_token_)) {
                out_ << ' ';
            }
            out_ << c->getText();
            at_line_start_ = false;
            // Treat as a generic word so spacing against the anchor works.
            last_emitted_token_ = HogQLLexer::IDENTIFIER;
            return;
        }
        // Free-standing comment on its own line.
        if (!at_line_start_) newline();
        flushIndent();
        out_ << c->getText();
        // Line comments already terminate with `\n` from the lexer; block
        // comments on their own line need an explicit newline.
        if (isLineComment(c)) {
            at_line_start_ = true;
            last_emitted_token_ = -1;
        } else {
            newline();
        }
    }

    // Trailing comments hug the line of their anchor. A `--` comment runs to
    // EOL and so forces a line break after itself; a block comment can sit
    // inline and let the next emission pick up normally.
    void emitTrailingComment(Token* c) {
        if (!at_line_start_ && last_emitted_token_ != -1) {
            out_ << ' ';
        }
        out_ << c->getText();
        if (isLineComment(c)) {
            at_line_start_ = true;
            last_emitted_token_ = -1;
        } else {
            // Mark as a word-class token so subsequent spacing inserts a space.
            at_line_start_ = false;
            last_emitted_token_ = HogQLLexer::IDENTIFIER;
        }
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
            // Grammar guarantees LPAREN/RPAREN when there's a selectSetStmt;
            // the `else` branches synthesize as a defensive fallback.
            if (auto* lp = ctx->LPAREN()) emitToken(lp->getSymbol());
            else emitRaw('(', HogQLLexer::LPAREN);
            indent_++;
            newline();
            formatSelectSetStmt(set);
            indent_--;
            newline();
            if (auto* rp = ctx->RPAREN()) emitToken(rp->getSymbol());
            else emitRaw(')', HogQLLexer::RPAREN);
        }
    }

    void formatSelectStmt(HogQLParser::SelectStmtContext* ctx) {
        if (auto* withCtx = ctx->withClause()) {
            formatWithClause(withCtx);
            newline();
        }

        emitToken(ctx->SELECT()->getSymbol());
        if (ctx->DISTINCT()) emitToken(ctx->DISTINCT()->getSymbol());
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
            emitToken(prew->PREWHERE()->getSymbol());
            indent_++;
            newline();
            emitSubtreeTokens(prew->columnExpr());
            indent_--;
        }
        if (auto* where = ctx->whereClause()) {
            newline();
            emitToken(where->WHERE()->getSymbol());
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
            emitToken(having->HAVING()->getSymbol());
            indent_++;
            newline();
            emitSubtreeTokens(having->columnExpr());
            indent_--;
        }
        if (auto* qual = ctx->qualifyClause()) {
            newline();
            emitToken(qual->QUALIFY()->getSymbol());
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
    // top-level columns. Otherwise emit inline. Emitting the *source* COMMA
    // terminals (rather than synthesizing `,`) lets `attachComments` propagate
    // any attached comments through `emitToken`.
    void formatSelectColumnList(HogQLParser::SelectColumnExprListBeforeFromContext* ctx) {
        if (!ctx) return;

        vector<HogQLParser::SelectColumnExprContext*> cols;
        vector<tree::TerminalNode*> commas;
        collectColumnsAndCommas(ctx, cols, commas);

        bool breakLines = cols.size() > COLUMN_BREAK_THRESHOLD;
        indent_++;
        for (size_t i = 0; i < cols.size(); i++) {
            if (i == 0) {
                if (breakLines) newline();
            } else {
                if (i - 1 < commas.size()) {
                    emitToken(commas[i - 1]->getSymbol());
                } else {
                    emitRaw(',', HogQLLexer::COMMA);
                }
                if (breakLines) newline();
            }
            emitSubtreeTokens(cols[i]);
        }
        indent_--;
    }

    // Grammar has two alternatives — TrailingComma keeps cols/commas as direct
    // children, Plain wraps them in a `selectColumnExprList`. Flatten both
    // shapes into ordered cols + commas vectors so the caller can iterate by
    // index pair.
    void collectColumnsAndCommas(HogQLParser::SelectColumnExprListBeforeFromContext* ctx,
                                 vector<HogQLParser::SelectColumnExprContext*>& cols,
                                 vector<tree::TerminalNode*>& commas) {
        auto visit = [&](tree::ParseTree* node) {
            for (auto* child : node->children) {
                if (auto* col = dynamic_cast<HogQLParser::SelectColumnExprContext*>(child)) {
                    cols.push_back(col);
                } else if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                    if (term->getSymbol()->getType() == HogQLLexer::COMMA) commas.push_back(term);
                }
            }
        };
        for (auto* child : ctx->children) {
            if (auto* col = dynamic_cast<HogQLParser::SelectColumnExprContext*>(child)) {
                cols.push_back(col);
            } else if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                if (term->getSymbol()->getType() == HogQLLexer::COMMA) commas.push_back(term);
            } else if (auto* list = dynamic_cast<HogQLParser::SelectColumnExprListContext*>(child)) {
                visit(list);
            }
        }
    }

    void formatWithClause(HogQLParser::WithClauseContext* ctx) {
        emitToken(ctx->WITH()->getSymbol());
        if (ctx->RECURSIVE()) emitToken(ctx->RECURSIVE()->getSymbol());
        auto* list = ctx->withExprList();
        if (!list) return;
        auto exprs = list->withExpr();
        vector<tree::TerminalNode*> commas;
        collectCommaTerminals(list, commas);
        bool breakLines = exprs.size() > 1;
        indent_++;
        for (size_t i = 0; i < exprs.size(); i++) {
            if (i == 0) {
                if (breakLines) newline();
            } else {
                if (i - 1 < commas.size()) {
                    emitToken(commas[i - 1]->getSymbol());
                } else {
                    emitRaw(',', HogQLLexer::COMMA);
                }
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
        emitToken(ctx->FROM()->getSymbol());
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
            emitToken(parens->LPAREN()->getSymbol());
            indent_++;
            newline();
            formatJoinExpr(parens->joinExpr());
            indent_--;
            newline();
            emitToken(parens->RPAREN()->getSymbol());
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
            emitToken(pos->POSITIONAL()->getSymbol());
            emitToken(pos->JOIN()->getSymbol());
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
            if (table->FINAL()) emitToken(table->FINAL()->getSymbol());
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
            emitToken(sub->LPAREN()->getSymbol());
            indent_++;
            newline();
            formatSelectSetStmt(sub->selectSetStmt());
            indent_--;
            newline();
            emitToken(sub->RPAREN()->getSymbol());
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
        // Header (`GROUP BY`) emitted via real tokens so leading comments fire.
        emitToken(ctx->GROUP()->getSymbol());
        emitToken(ctx->BY()->getSymbol());
        indent_++;
        newline();
        // The body alternative varies (ALL, CUBE/ROLLUP(list), GROUPING SETS,
        // plain columnExprList). Emit the remaining children inline; the
        // leading GROUP/BY terminals are the only ones we skip.
        for (auto* child : ctx->children) {
            if (auto* term = dynamic_cast<tree::TerminalNode*>(child)) {
                int t = term->getSymbol()->getType();
                if (t == HogQLLexer::GROUP || t == HogQLLexer::BY) continue;
                emitToken(term->getSymbol());
            } else {
                emitSubtreeTokens(child);
            }
        }
        indent_--;
    }

    void formatOrderByClause(HogQLParser::OrderByClauseContext* ctx) {
        emitToken(ctx->ORDER()->getSymbol());
        emitToken(ctx->BY()->getSymbol());
        auto* list = ctx->orderExprList();
        if (!list) return;
        auto exprs = list->orderExpr();
        vector<tree::TerminalNode*> commas;
        collectCommaTerminals(list, commas);
        bool breakLines = exprs.size() > COLUMN_BREAK_THRESHOLD;
        indent_++;
        for (size_t i = 0; i < exprs.size(); i++) {
            if (i == 0) {
                if (breakLines) newline();
            } else {
                if (i - 1 < commas.size()) {
                    emitToken(commas[i - 1]->getSymbol());
                } else {
                    emitRaw(',', HogQLLexer::COMMA);
                }
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

        HogQLFormatter formatter(input, &tokens);
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
