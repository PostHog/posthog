// parser_core.cpp - Pure C++ HogQL Parser Core
// This file contains the core parser logic that returns JSON representations of ASTs.
// It can be compiled for Python (via parser_python.cpp), WebAssembly, or other platforms.

#include <boost/algorithm/string.hpp>
#include <sstream>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "json_builder.h"
#include "string.h"

#define VISIT(RULE) any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                            \
  VISIT(RULE) {                                            \
    throw NotImplementedError("Unsupported rule: " #RULE); \
  }

using namespace std;

// JSON UTILS

// Helper: Add position information to JSON object from ParserRuleContext
void addPositionInfo(JSONBuilder& json, antlr4::ParserRuleContext* ctx) {
  if (!ctx) return;

  auto start_token = ctx->getStart();
  auto stop_token = ctx->getStop();

  if (start_token) {
    JSONBuilder::Position start = {
        start_token->getLine(), start_token->getCharPositionInLine(), start_token->getStartIndex()
    };
    json.addPosition("start", start);
  }

  if (stop_token) {
    JSONBuilder::Position end = {
        stop_token->getLine(), stop_token->getCharPositionInLine() + stop_token->getText().length(),
        stop_token->getStopIndex() + 1
    };
    json.addPosition("end", end);
  }
}

// Helper: Add position from single token
void addPositionInfo(JSONBuilder& json, const string& key, antlr4::Token* token) {
  if (!token) return;

  JSONBuilder::Position pos = {token->getLine(), token->getCharPositionInLine(), token->getStartIndex()};
  json.addPosition(key, pos);
}

// Helper: Add end position from single token
void addEndPositionInfo(JSONBuilder& json, antlr4::Token* token) {
  if (!token) return;

  JSONBuilder::Position end = {
      token->getLine(), token->getCharPositionInLine() + token->getText().length(), token->getStopIndex() + 1
  };
  json.addPosition("end", end);
}

// Helper: Create JSON array from vector of strings
void addStringArray(JSONBuilder& json, const string& key, const vector<string>& items) {
  json.addKey(key);
  json.startArray();
  for (const auto& item : items) {
    json.addString(item);
  }
  json.endArray();
}

// Helper: Build a JSON error object
string buildJSONError(const char* error_type, const string& message, size_t start, size_t end) {
  JSONBuilder json;
  json.startObject();
  json.addKey("error");
  json.addBool(true);
  json.addKey("type");
  json.addString(error_type);
  json.addKey("message");
  json.addString(message);
  json.addPosition("start", {0, 0, start});
  json.addPosition("end", {0, 0, end});
  json.endObject();
  return json.toString();
}

// PARSING AND AST CONVERSION

class HogQLParseTreeConverter : public HogQLParserBaseVisitor {
 private:
  bool is_internal;

  const vector<string> RESERVED_KEYWORDS = {"true", "false", "null", "team_id"};

 public:
  HogQLParseTreeConverter(bool is_internal) : is_internal(is_internal) {}

  any visit(antlr4::tree::ParseTree* tree) override {
    // Find the start and stop indices of the parse tree node
    size_t start;
    size_t stop;
    auto token = dynamic_cast<antlr4::Token*>(tree);
    if (token) {
      start = token->getStartIndex();
      stop = token->getStopIndex();
    } else {
      auto ctx = dynamic_cast<antlr4::ParserRuleContext*>(tree);
      if (!ctx) {
        throw ParsingError("Parse tree node is neither a Token nor a ParserRuleContext");
      }
      start = ctx->getStart()->getStartIndex();
      stop = ctx->getStop()->getStopIndex();
    }
    // Visit the parse tree node (while making sure that errors have spans)
    any node;
    try {
      node = tree->accept(this);
    } catch (const SyntaxError& e) {
      // If start and end are unset, rethrow with the current start and stop
      if (!is_internal && e.start == 0 && e.end == 0) {
        throw SyntaxError(e.what(), start, stop + 1);
      }
      throw;
    }
    // For JSON output, position info is added inline in each VISIT method
    return node;
  }

  // Entry point for external callers - wraps errors in JSON
  string visitAsJSONFinal(antlr4::tree::ParseTree* tree) {
    try {
      return visitAsJSON(tree);
    } catch (const SyntaxError& e) {
      return buildJSONError("SyntaxError", e.what(), e.start, e.end);
    } catch (const NotImplementedError& e) {
      return buildJSONError("NotImplementedError", e.what(), e.start, e.end);
    } catch (const ParsingError& e) {
      return buildJSONError("ParsingError", e.what(), e.start, e.end);
    } catch (const bad_any_cast& e) {
      return buildJSONError("ParsingError", "Parsing failed due to bad type casting", 0, 0);
    } catch (...) {
      return buildJSONError("ParsingError", "Unknown parsing error occurred", 0, 0);
    }
  }

  // JSON helper methods
  string visitAsJSON(antlr4::tree::ParseTree* tree) {
    if (!tree) {
      return "null";
    }
    return any_cast<string>(visit(tree));
  }

  string visitAsJSONOrNull(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      return "null";
    }
    return visitAsJSON(tree);
  }

  string visitAsJSONOrEmptyArray(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      return "[]";
    }
    return visitAsJSON(tree);
  }

  template <typename T>
  string visitJSONArrayOfObjects(vector<T> trees) {
    JSONBuilder json;
    json.startArray();
    for (auto tree : trees) {
      string item_json = visitAsJSON(tree);
      json.addRawJSON(item_json);
    }
    json.endArray();
    return json.toString();
  }

  string visitAsString(antlr4::tree::ParseTree* tree) { return any_cast<string>(visit(tree)); }

  template <typename T>
  vector<string> visitAsVectorOfStrings(vector<T> tree) {
    vector<string> ret;
    ret.reserve(tree.size());
    for (auto child : tree) {
      ret.push_back(visitAsString(child));
    }
    return ret;
  }

  template <typename T>
  vector<string> visitAsVectorOfJSON(vector<T> trees) {
    vector<string> ret;
    ret.reserve(trees.size());
    for (auto tree : trees) {
      ret.push_back(visitAsJSON(tree));
    }
    return ret;
  }

  VISIT(Program) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Program");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("declarations");
    json.startArray();
    auto declaration_ctxs = ctx->declaration();
    for (auto declaration_ctx : declaration_ctxs) {
      if (declaration_ctx->statement() && declaration_ctx->statement()->emptyStmt()) {
        continue;
      }
      json.addRawJSON(visitAsJSON(declaration_ctx));
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(Declaration) {
    auto var_decl_ctx = ctx->varDecl();
    if (var_decl_ctx) {
      return visit(var_decl_ctx);
    }
    auto statement_ctx = ctx->statement();
    if (statement_ctx) {
      return visit(statement_ctx);
    }
    throw ParsingError("Declaration must be either a varDecl or a statement");
  }

  VISIT(Expression) { return visit(ctx->columnExpr()); }

  VISIT(VarDecl) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("VariableDeclaration");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    string name = visitAsString(ctx->identifier());
    json.addKey("name");
    json.addString(name);
    json.addKey("expr");
    json.addRawJSON(visitAsJSONOrNull(ctx->expression()));
    json.endObject();
    return json.toString();
  }

  VISIT(VarAssignment) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("VariableAssignment");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("left");
    json.addRawJSON(visitAsJSON(ctx->expression(0)));
    json.addKey("right");
    json.addRawJSON(visitAsJSON(ctx->expression(1)));
    json.endObject();
    return json.toString();
  }

  VISIT(Statement) {
    auto return_stmt_ctx = ctx->returnStmt();
    if (return_stmt_ctx) {
      return visit(return_stmt_ctx);
    }

    auto throw_stmt_ctx = ctx->throwStmt();
    if (throw_stmt_ctx) {
      return visit(throw_stmt_ctx);
    }

    auto try_catch_stmt_ctx = ctx->tryCatchStmt();
    if (try_catch_stmt_ctx) {
      return visit(try_catch_stmt_ctx);
    }

    auto if_stmt_ctx = ctx->ifStmt();
    if (if_stmt_ctx) {
      return visit(if_stmt_ctx);
    }

    auto while_stmt_ctx = ctx->whileStmt();
    if (while_stmt_ctx) {
      return visit(while_stmt_ctx);
    }

    auto for_stmt_ctx = ctx->forStmt();
    if (for_stmt_ctx) {
      return visit(for_stmt_ctx);
    }

    auto for_in_stmt_ctx = ctx->forInStmt();
    if (for_in_stmt_ctx) {
      return visit(for_in_stmt_ctx);
    }

    auto func_stmt_ctx = ctx->funcStmt();
    if (func_stmt_ctx) {
      return visit(func_stmt_ctx);
    }

    auto var_assignment_ctx = ctx->varAssignment();
    if (var_assignment_ctx) {
      return visit(var_assignment_ctx);
    }

    auto block_ctx = ctx->block();
    if (block_ctx) {
      return visit(block_ctx);
    }

    auto expr_stmt_ctx = ctx->exprStmt();
    if (expr_stmt_ctx) {
      return visit(expr_stmt_ctx);
    }

    auto empty_stmt_ctx = ctx->emptyStmt();
    if (empty_stmt_ctx) {
      return visit(empty_stmt_ctx);
    }

    throw ParsingError(
        "Statement must be one of returnStmt, throwStmt, tryCatchStmt, ifStmt, whileStmt, forStmt, forInStmt, "
        "funcStmt, "
        "varAssignment, block, exprStmt, or emptyStmt"
    );
  }

  VISIT(ExprStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ExprStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->expression()));
    json.endObject();
    return json.toString();
  }

  VISIT(ReturnStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ReturnStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSONOrNull(ctx->expression()));
    json.endObject();
    return json.toString();
  }

  VISIT(ThrowStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ThrowStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSONOrNull(ctx->expression()));
    json.endObject();
    return json.toString();
  }

  VISIT(CatchBlock) {
    // CatchBlock returns an array [catch_var, catch_type, catch_stmt]
    JSONBuilder json;
    json.startArray();

    if (ctx->catchVar) {
      string catch_var = visitAsString(ctx->catchVar);
      json.addString(catch_var);
    } else {
      json.addNull();
    }

    if (ctx->catchType) {
      string catch_type = visitAsString(ctx->catchType);
      json.addString(catch_type);
    } else {
      json.addNull();
    }

    json.addRawJSON(visitAsJSON(ctx->catchStmt));
    json.endArray();
    return json.toString();
  }

  VISIT(TryCatchStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("TryCatchStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("try_stmt");
    json.addRawJSON(visitAsJSON(ctx->tryStmt));
    json.addKey("catches");
    json.startArray();
    auto catch_block_ctxs = ctx->catchBlock();
    for (auto catch_block_ctx : catch_block_ctxs) {
      json.addRawJSON(visitAsJSON(catch_block_ctx));
    }
    json.endArray();
    json.addKey("finally_stmt");
    json.addRawJSON(visitAsJSONOrNull(ctx->finallyStmt));
    json.endObject();
    return json.toString();
  }

  VISIT(IfStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("IfStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->expression()));
    json.addKey("then");
    json.addRawJSON(visitAsJSON(ctx->statement(0)));
    json.addKey("else_");
    json.addRawJSON(visitAsJSONOrNull(ctx->statement(1)));
    json.endObject();
    return json.toString();
  }

  VISIT(WhileStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("WhileStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->expression()));
    json.addKey("body");
    json.addRawJSON(visitAsJSONOrNull(ctx->statement()));
    json.endObject();
    return json.toString();
  }

  VISIT(ForStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ForStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    json.addKey("initializer");
    if (ctx->initializerVarDeclr) {
      json.addRawJSON(visitAsJSON(ctx->initializerVarDeclr));
    } else if (ctx->initializerVarAssignment) {
      json.addRawJSON(visitAsJSON(ctx->initializerVarAssignment));
    } else if (ctx->initializerExpression) {
      json.addRawJSON(visitAsJSON(ctx->initializerExpression));
    } else {
      json.addNull();
    }

    json.addKey("condition");
    json.addRawJSON(visitAsJSONOrNull(ctx->condition));

    json.addKey("increment");
    if (ctx->incrementVarDeclr) {
      json.addRawJSON(visitAsJSON(ctx->incrementVarDeclr));
    } else if (ctx->incrementVarAssignment) {
      json.addRawJSON(visitAsJSON(ctx->incrementVarAssignment));
    } else if (ctx->incrementExpression) {
      json.addRawJSON(visitAsJSON(ctx->incrementExpression));
    } else {
      json.addNull();
    }

    json.addKey("body");
    json.addRawJSON(visitAsJSON(ctx->statement()));
    json.endObject();
    return json.toString();
  }

  VISIT(ForInStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ForInStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    string first_identifier = visitAsString(ctx->identifier(0));
    string second_identifier;
    if (ctx->identifier(1)) {
      second_identifier = visitAsString(ctx->identifier(1));
      json.addKey("keyVar");
      json.addString(first_identifier);
      json.addKey("valueVar");
      json.addString(second_identifier);
    } else {
      json.addKey("keyVar");
      json.addNull();
      json.addKey("valueVar");
      json.addString(first_identifier);
    }

    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->expression()));
    json.addKey("body");
    json.addRawJSON(visitAsJSON(ctx->statement()));
    json.endObject();
    return json.toString();
  }

  VISIT(FuncStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Function");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    string name = visitAsString(ctx->identifier());
    json.addKey("name");
    json.addString(name);

    json.addKey("params");
    auto identifier_list_ctx = ctx->identifierList();
    if (identifier_list_ctx) {
      vector<string> paramList = any_cast<vector<string>>(visit(ctx->identifierList()));
      json.startArray();
      for (const auto& param : paramList) {
        json.addString(param);
      }
      json.endArray();
    } else {
      json.startArray();
      json.endArray();
    }

    json.addKey("body");
    json.addRawJSON(visitAsJSON(ctx->block()));
    json.endObject();
    return json.toString();
  }

  VISIT(KvPairList) { return visitJSONArrayOfObjects(ctx->kvPair()); }

  VISIT(KvPair) {
    // KvPair returns an array [key, value]
    JSONBuilder json;
    json.startArray();
    json.addRawJSON(visitAsJSON(ctx->expression(0)));
    json.addRawJSON(visitAsJSON(ctx->expression(1)));
    json.endArray();
    return json.toString();
  }

  VISIT(IdentifierList) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(EmptyStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ExprStatement");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addNull();
    json.endObject();
    return json.toString();
  }

  VISIT(Block) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Block");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("declarations");
    json.startArray();
    auto declaration_ctxs = ctx->declaration();
    for (auto declaration_ctx : declaration_ctxs) {
      if (!declaration_ctx->statement() || !declaration_ctx->statement()->emptyStmt()) {
        json.addRawJSON(visitAsJSON(declaration_ctx));
      }
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  // HogQL rules

  VISIT(Select) {
    auto select_set_stmt_ctx = ctx->selectSetStmt();
    if (select_set_stmt_ctx) {
      return visit(select_set_stmt_ctx);
    }

    auto select_stmt_ctx = ctx->selectStmt();
    if (select_stmt_ctx) {
      return visit(select_stmt_ctx);
    }

    return visit(ctx->hogqlxTagElement());
  }

  VISIT(SelectStmtWithParens) {
    auto select_stmt_ctx = ctx->selectStmt();
    if (select_stmt_ctx) {
      return visit(select_stmt_ctx);
    }

    auto placeholder_ctx = ctx->placeholder();
    if (placeholder_ctx) {
      return visit(placeholder_ctx);
    }

    return visit(ctx->selectSetStmt());
  }

  VISIT(SelectSetStmt) {
    auto subsequent_clauses = ctx->subsequentSelectSetClause();

    if (subsequent_clauses.empty()) {
      return visit(ctx->selectStmtWithParens());
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("SelectSetQuery");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    json.addKey("initial_select_query");
    json.addRawJSON(visitAsJSON(ctx->selectStmtWithParens()));

    json.addKey("subsequent_select_queries");
    json.startArray();
    for (auto subsequent : subsequent_clauses) {
      const char* set_operator;
      if (subsequent->UNION() && subsequent->ALL()) {
        set_operator = "UNION ALL";
      } else if (subsequent->UNION() && subsequent->DISTINCT()) {
        set_operator = "UNION DISTINCT";
      } else if (subsequent->INTERSECT() && subsequent->DISTINCT()) {
        set_operator = "INTERSECT DISTINCT";
      } else if (subsequent->INTERSECT()) {
        set_operator = "INTERSECT";
      } else if (subsequent->EXCEPT()) {
        set_operator = "EXCEPT";
      } else {
        throw SyntaxError(
            "Set operator must be one of UNION ALL, UNION DISTINCT, INTERSECT, INTERSECT DISTINCT, and EXCEPT"
        );
      }

      JSONBuilder node_json;
      node_json.startObject();
      node_json.addNodeType("SelectSetNode");
      node_json.addKey("select_query");
      node_json.addRawJSON(visitAsJSON(subsequent->selectStmtWithParens()));
      node_json.addKey("set_operator");
      node_json.addString(set_operator);
      node_json.endObject();
      json.addRawJSON(node_json.toString());
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(SelectStmt) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("SelectQuery");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    // Add basic query fields
    json.addKey("ctes");
    json.addRawJSON(visitAsJSONOrNull(ctx->withClause()));
    json.addKey("select");
    json.addRawJSON(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    json.addKey("distinct");
    if (ctx->DISTINCT()) {
      json.addBool(true);
    } else {
      json.addNull();
    }
    json.addKey("select_from");
    json.addRawJSON(visitAsJSONOrNull(ctx->fromClause()));
    json.addKey("where");
    json.addRawJSON(visitAsJSONOrNull(ctx->whereClause()));
    json.addKey("prewhere");
    json.addRawJSON(visitAsJSONOrNull(ctx->prewhereClause()));
    json.addKey("having");
    json.addRawJSON(visitAsJSONOrNull(ctx->havingClause()));
    json.addKey("group_by");
    json.addRawJSON(visitAsJSONOrNull(ctx->groupByClause()));
    json.addKey("order_by");
    json.addRawJSON(visitAsJSONOrNull(ctx->orderByClause()));

    // Handle window clause
    auto window_clause_ctx = ctx->windowClause();
    if (window_clause_ctx) {
      auto window_expr_ctxs = window_clause_ctx->windowExpr();
      auto identifier_ctxs = window_clause_ctx->identifier();
      if (window_expr_ctxs.size() != identifier_ctxs.size()) {
        throw ParsingError("WindowClause must have a matching number of window exprs and identifiers");
      }
      json.addKey("window_exprs");
      json.startObject();
      for (size_t i = 0; i < window_expr_ctxs.size(); i++) {
        string identifier = visitAsString(identifier_ctxs[i]);
        json.addKey(identifier);
        json.addRawJSON(visitAsJSON(window_expr_ctxs[i]));
      }
      json.endObject();
    }

    // Handle offset and limit clauses
    auto limit_and_offset_clause_ctx = ctx->limitAndOffsetClause();
    auto offset_only_clause_ctx = ctx->offsetOnlyClause();

    if (offset_only_clause_ctx && !limit_and_offset_clause_ctx) {
      json.addKey("offset");
      json.addRawJSON(visitAsJSON(offset_only_clause_ctx));
    }

    if (limit_and_offset_clause_ctx) {
      json.addKey("limit");
      json.addRawJSON(visitAsJSON(limit_and_offset_clause_ctx->columnExpr(0)));

      auto offset_ctx = limit_and_offset_clause_ctx->columnExpr(1);
      if (offset_ctx) {
        json.addKey("offset");
        json.addRawJSON(visitAsJSON(offset_ctx));
      }

      if (limit_and_offset_clause_ctx->WITH() && limit_and_offset_clause_ctx->TIES()) {
        json.addKey("limit_with_ties");
        json.addBool(true);
      }
    }

    // Handle limit_by clause
    auto limit_by_clause_ctx = ctx->limitByClause();
    if (limit_by_clause_ctx) {
      json.addKey("limit_by");
      json.addRawJSON(visitAsJSON(limit_by_clause_ctx));
    }

    // Handle array_join clause
    auto array_join_clause_ctx = ctx->arrayJoinClause();
    if (array_join_clause_ctx) {
      string select_from_json = visitAsJSONOrNull(ctx->fromClause());
      if (select_from_json == "null") {
        throw SyntaxError("Using ARRAY JOIN without a FROM clause is not permitted");
      }

      json.addKey("array_join_op");
      if (array_join_clause_ctx->LEFT()) {
        json.addString("LEFT ARRAY JOIN");
      } else if (array_join_clause_ctx->INNER()) {
        json.addString("INNER ARRAY JOIN");
      } else {
        json.addString("ARRAY JOIN");
      }

      auto array_join_arrays_ctx = array_join_clause_ctx->columnExprList();
      auto array_join_exprs = array_join_arrays_ctx->columnExpr();

      // Validate that all array join expressions have aliases
      for (size_t i = 0; i < array_join_exprs.size(); i++) {
        string expr_json = visitAsJSON(array_join_exprs[i]);
        // Simple check: see if the JSON contains "node":"Alias"
        if (expr_json.find("\"node\":\"Alias\"") == string::npos) {
          auto relevant_column_expr_ctx = array_join_exprs[i];
          throw SyntaxError(
              "ARRAY JOIN arrays must have an alias", relevant_column_expr_ctx->getStart()->getStartIndex(),
              relevant_column_expr_ctx->getStop()->getStopIndex() + 1
          );
        }
      }

      json.addKey("array_join_list");
      json.addRawJSON(visitAsJSON(array_join_arrays_ctx));
    }

    // Check for unsupported clauses
    if (ctx->topClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.topClause()");
    }
    if (ctx->settingsClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.settingsClause()");
    }

    json.endObject();
    return json.toString();
  }

  VISIT(WithClause) { return visit(ctx->withExprList()); }

  VISIT_UNSUPPORTED(TopClause)

  VISIT(FromClause) { return visit(ctx->joinExpr()); }

  VISIT_UNSUPPORTED(ArrayJoinClause)

  VISIT_UNSUPPORTED(WindowClause)

  VISIT(PrewhereClause) { return visit(ctx->columnExpr()); }

  VISIT(WhereClause) { return visit(ctx->columnExpr()); }

  VISIT(GroupByClause) { return visit(ctx->columnExprList()); }

  VISIT(HavingClause) { return visit(ctx->columnExpr()); }

  VISIT(OrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(LimitByClause) {
    // LimitExpr returns either single JSON or a JSON array [limit, offset]
    string limit_expr_result = visitAsJSON(ctx->limitExpr());
    string exprs = visitAsJSON(ctx->columnExprList());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("LimitByExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    // Check if limit_expr_result is an array (contains both n and offset_value)
    if (limit_expr_result[0] == '[') {
      // It's an array, need to extract the two values
      // Parse the JSON array to get n and offset_value by counting braces
      int brace_count = 0;
      size_t comma_pos = string::npos;
      for (size_t i = 1; i < limit_expr_result.length(); i++) {
        if (limit_expr_result[i] == '{')
          brace_count++;
        else if (limit_expr_result[i] == '}')
          brace_count--;
        else if (limit_expr_result[i] == ',' && brace_count == 0) {
          comma_pos = i;
          break;
        }
      }
      if (comma_pos != string::npos) {
        string n = limit_expr_result.substr(1, comma_pos - 1);  // Skip '[' and get until ','
        string offset_value = limit_expr_result.substr(
            comma_pos + 1, limit_expr_result.length() - comma_pos - 2
        );  // Get after ',' until ']'
        json.addKey("n");
        json.addRawJSON(n);
        json.addKey("offset_value");
        json.addRawJSON(offset_value);
      } else {
        throw ParsingError("Invalid array format from limitExpr");
      }
    } else {
      // It's a single value, use as n with null offset_value
      json.addKey("n");
      json.addRawJSON(limit_expr_result);
      json.addKey("offset_value");
      json.addNull();
    }

    json.addKey("exprs");
    json.addRawJSON(exprs);
    json.endObject();
    return json.toString();
  }

  VISIT(LimitExpr) {
    string first = visitAsJSON(ctx->columnExpr(0));

    // If no second expression, just return the first
    if (!ctx->columnExpr(1)) {
      return first;
    }

    // We have both limit and offset - return as a simple array
    string second = visitAsJSON(ctx->columnExpr(1));

    JSONBuilder json;
    json.startArray();
    if (ctx->COMMA()) {
      // For "LIMIT a, b" syntax: a is offset, b is limit
      json.addRawJSON(second);  // offset
      json.addRawJSON(first);   // limit
    } else {
      // For "LIMIT a OFFSET b" syntax: a is limit, b is offset
      json.addRawJSON(first);   // limit
      json.addRawJSON(second);  // offset
    }
    json.endArray();
    return json.toString();
  }

  VISIT(OffsetOnlyClause) { return visitAsJSON(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ProjectionOrderByClause)

  VISIT_UNSUPPORTED(LimitAndOffsetClause)  // We handle this directly in the SelectStmt visitor

  VISIT_UNSUPPORTED(SettingsClause)

  // Helper: Chain two JOIN expressions together by finding the end of join1's chain
  string chainJoinExprs(const string& join1_json, const string& join2_json) {
    // Parse join1 to find the deepest next_join field and replace null with join2
    // For simplicity, we'll use string manipulation to find and replace the last "next_join":null
    size_t pos = join1_json.rfind("\"next_join\":null");
    if (pos == string::npos) {
      // If we've exceeded depth, throw error
      throw ParsingError("Maximum recursion depth exceeded during JOIN parsing");
    }

    string result = join1_json;
    result.replace(pos, 16, "\"next_join\":" + join2_json);  // 16 is length of "next_join":null
    return result;
  }

  VISIT(JoinExprOp) {
    auto join_op_ctx = ctx->joinOp();
    string join_op;
    if (join_op_ctx) {
      join_op = visitAsString(join_op_ctx);
      join_op.append(" JOIN");
    } else {
      join_op = "JOIN";
    }

    // Get join2 and add the join_type and constraint to it
    string join2_json = visitAsJSON(ctx->joinExpr(1));
    string constraint_json = visitAsJSON(ctx->joinConstraintClause());

    // We need to inject join_type and constraint into join2_json
    // Find the position after the opening brace and node type
    size_t insert_pos = join2_json.find(",", join2_json.find("\"node\""));
    if (insert_pos != string::npos) {
      string injection =
          "\"join_type\":\"" + JSONBuilder::escapeString(join_op) + "\",\"constraint\":" + constraint_json + ",";
      join2_json.insert(insert_pos + 1, injection);
    }

    string join1_json = visitAsJSON(ctx->joinExpr(0));

    // Chain the joins together
    return chainJoinExprs(join1_json, join2_json);
  }

  VISIT(JoinExprTable) {
    string table_json = visitAsJSON(ctx->tableExpr());
    string sample_json = visitAsJSONOrNull(ctx->sampleClause());
    bool table_final = ctx->FINAL();

    // Check if table is already a JoinExpr by looking at the START of the JSON
    bool is_table_join_expr = table_json.substr(0, 30).find("\"node\":\"JoinExpr\"") != string::npos;

    if (is_table_join_expr) {
      // Inject sample and table_final into the existing JoinExpr before the closing brace
      size_t insert_pos = table_json.rfind("}");
      if (insert_pos != string::npos) {
        string injection = ",\"sample\":" + sample_json + ",\"table_final\":" + (table_final ? "true" : "null");
        table_json.insert(insert_pos, injection);
      }
      return table_json;
    } else {
      // Create a new JoinExpr wrapping the table
      // Note: join_type/constraint will be injected by JoinExprOp before the closing }
      JSONBuilder json;
      json.startObject();
      json.addNodeType("JoinExpr");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("table");
      json.addRawJSON(table_json);
      json.addKey("table_final");
      if (table_final) {
        json.addBool(true);
      } else {
        json.addNull();
      }
      json.addKey("sample");
      json.addRawJSON(sample_json);
      json.addKey("next_join");
      json.addNull();
      json.addKey("alias");
      json.addNull();
      json.endObject();
      return json.toString();
    }
  }

  VISIT(JoinExprParens) { return visit(ctx->joinExpr()); }

  VISIT(JoinExprCrossOp) {
    string join_type = "CROSS JOIN";

    string join2_json = visitAsJSON(ctx->joinExpr(1));
    string join1_json = visitAsJSON(ctx->joinExpr(0));

    // Inject join_type into join2
    size_t insert_pos = join2_json.find(",", join2_json.find("\"node\""));
    if (insert_pos != string::npos) {
      string injection = "\"join_type\":\"" + join_type + "\",";
      join2_json.insert(insert_pos + 1, injection);
    }

    // Chain the joins
    return chainJoinExprs(join1_json, join2_json);
  }

  VISIT(JoinOpInner) {
    vector<string> tokens;
    if (ctx->ALL()) {
      tokens.push_back("ALL");
    }
    if (ctx->ANY()) {
      tokens.push_back("ANY");
    }
    if (ctx->ASOF()) {
      tokens.push_back("ASOF");
    }
    tokens.push_back("INNER");
    return boost::algorithm::join(tokens, " ");
  }

  VISIT(JoinOpLeftRight) {
    vector<string> tokens;
    if (ctx->LEFT()) {
      tokens.push_back("LEFT");
    }
    if (ctx->RIGHT()) {
      tokens.push_back("RIGHT");
    }
    if (ctx->OUTER()) {
      tokens.push_back("OUTER");
    }
    if (ctx->SEMI()) {
      tokens.push_back("SEMI");
    }
    if (ctx->ALL()) {
      tokens.push_back("ALL");
    }
    if (ctx->ANTI()) {
      tokens.push_back("ANTI");
    }
    if (ctx->ANY()) {
      tokens.push_back("ANY");
    }
    if (ctx->ASOF()) {
      tokens.push_back("ASOF");
    }
    return boost::algorithm::join(tokens, " ");
  }

  VISIT(JoinOpFull) {
    vector<string> tokens;
    if (ctx->FULL()) {
      tokens.push_back("FULL");
    }
    if (ctx->OUTER()) {
      tokens.push_back("OUTER");
    }
    if (ctx->ALL()) {
      tokens.push_back("ALL");
    }
    if (ctx->ANY()) {
      tokens.push_back("ANY");
    }
    return boost::algorithm::join(tokens, " ");
  }

  VISIT_UNSUPPORTED(JoinOpCross)

  VISIT(JoinConstraintClause) {
    string column_expr_list_json = visitAsJSON(ctx->columnExprList());

    // Check if we have multiple expressions (array with more than one element)
    // Simple check: count commas at depth 0
    int bracket_depth = 0;
    int expr_count = 1;
    for (char c : column_expr_list_json) {
      if (c == '[' || c == '{')
        bracket_depth++;
      else if (c == ']' || c == '}')
        bracket_depth--;
      else if (c == ',' && bracket_depth == 1)
        expr_count++;
    }

    if (expr_count > 1) {
      throw NotImplementedError("Unsupported: JOIN ... ON with multiple expressions");
    }

    // Extract the single expression from the array
    size_t first_brace = column_expr_list_json.find('{');
    size_t last_brace = column_expr_list_json.rfind('}');
    string expr_json = column_expr_list_json.substr(first_brace, last_brace - first_brace + 1);

    JSONBuilder json;
    json.startObject();
    json.addNodeType("JoinConstraint");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("constraint_type");
    json.addString(ctx->USING() ? "USING" : "ON");
    json.endObject();
    return json.toString();
  }

  VISIT(SampleClause) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("SampleExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("sample_value");
    json.addRawJSON(visitAsJSON(ctx->ratioExpr(0)));
    json.addKey("offset_value");
    json.addRawJSON(visitAsJSONOrNull(ctx->ratioExpr(1)));
    json.endObject();
    return json.toString();
  }

  VISIT(OrderExprList) { return visitJSONArrayOfObjects(ctx->orderExpr()); }

  VISIT(OrderExpr) {
    const char* order = ctx->DESC() || ctx->DESCENDING() ? "DESC" : "ASC";
    JSONBuilder json;
    json.startObject();
    json.addNodeType("OrderExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.addKey("order");
    json.addString(order);
    json.endObject();
    return json.toString();
  }

  VISIT(RatioExpr) {
    auto placeholder_ctx = ctx->placeholder();
    if (placeholder_ctx) {
      return visitAsJSON(placeholder_ctx);
    }

    auto number_literal_ctxs = ctx->numberLiteral();

    if (number_literal_ctxs.size() > 2) {
      throw ParsingError("RatioExpr must have at most two number literals");
    } else if (number_literal_ctxs.size() == 0) {
      throw ParsingError("RatioExpr must have at least one number literal");
    }

    auto left_ctx = number_literal_ctxs[0];
    auto right_ctx = ctx->SLASH() && number_literal_ctxs.size() > 1 ? number_literal_ctxs[1] : NULL;

    JSONBuilder json;
    json.startObject();
    json.addNodeType("RatioExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("left");
    json.addRawJSON(visitAsJSON(left_ctx));
    json.addKey("right");
    json.addRawJSON(visitAsJSONOrNull(right_ctx));
    json.endObject();
    return json.toString();
  }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  VISIT(WindowExpr) {
    auto frame_ctx = ctx->winFrameClause();
    string frame_json = visitAsJSONOrNull(frame_ctx);

    // Check if frame is an array (tuple of [start, end])
    bool is_frame_array = frame_json[0] == '[';
    string frame_start_json;
    string frame_end_json;

    if (is_frame_array) {
      // Extract start and end from array like [{...},{...}]
      // Find the comma between the two objects by counting braces
      int brace_count = 0;
      size_t comma_pos = string::npos;
      for (size_t i = 1; i < frame_json.length(); i++) {
        if (frame_json[i] == '{')
          brace_count++;
        else if (frame_json[i] == '}')
          brace_count--;
        else if (frame_json[i] == ',' && brace_count == 0) {
          comma_pos = i;
          break;
        }
      }
      if (comma_pos != string::npos) {
        frame_start_json = frame_json.substr(1, comma_pos - 1);                                  // Skip '['
        frame_end_json = frame_json.substr(comma_pos + 1, frame_json.length() - comma_pos - 2);  // Skip ']'
      } else {
        throw ParsingError("WindowExpr frame must be an array of size 2");
      }
    } else {
      frame_start_json = frame_json;
      frame_end_json = "null";
    }

    string frame_method;
    if (frame_ctx && frame_ctx->RANGE()) {
      frame_method = "RANGE";
    } else if (frame_ctx && frame_ctx->ROWS()) {
      frame_method = "ROWS";
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("WindowExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("partition_by");
    json.addRawJSON(visitAsJSONOrNull(ctx->winPartitionByClause()));
    json.addKey("order_by");
    json.addRawJSON(visitAsJSONOrNull(ctx->winOrderByClause()));
    json.addKey("frame_method");
    if (!frame_method.empty()) {
      json.addString(frame_method);
    } else {
      json.addNull();
    }
    json.addKey("frame_start");
    json.addRawJSON(frame_start_json);
    json.addKey("frame_end");
    json.addRawJSON(frame_end_json);
    json.endObject();
    return json.toString();
  }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  VISIT(FrameBetween) {
    // Return an array with [start, end]
    JSONBuilder json;
    json.startArray();
    json.addRawJSON(visitAsJSON(ctx->winFrameBound(0)));
    json.addRawJSON(visitAsJSON(ctx->winFrameBound(1)));
    json.endArray();
    return json.toString();
  }

  VISIT(WinFrameBound) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("WindowFrameExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    if (ctx->PRECEDING() || ctx->FOLLOWING()) {
      json.addKey("frame_type");
      json.addString(ctx->PRECEDING() ? "PRECEDING" : "FOLLOWING");
      json.addKey("frame_value");
      if (ctx->numberLiteral()) {
        // Extract the value from the Constant node
        string constant_json = visitAsJSON(ctx->numberLiteral());
        // Parse out the value field from the JSON
        size_t value_pos = constant_json.find("\"value\":");
        if (value_pos != string::npos) {
          size_t value_start = value_pos + 8;  // Skip "value":
          size_t value_end = constant_json.find_first_of(",}", value_start);
          string value_str = constant_json.substr(value_start, value_end - value_start);
          json.addRawJSON(value_str);
        } else {
          json.addNull();
        }
      } else {
        json.addNull();
      }
    } else {
      json.addKey("frame_type");
      json.addString("CURRENT ROW");
    }

    json.endObject();
    return json.toString();
  }

  VISIT(Expr) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnTypeExprSimple)

  VISIT_UNSUPPORTED(ColumnTypeExprNested)

  VISIT_UNSUPPORTED(ColumnTypeExprEnum)

  VISIT_UNSUPPORTED(ColumnTypeExprComplex)

  VISIT_UNSUPPORTED(ColumnTypeExprParam)

  VISIT(ColumnExprList) { return visitJSONArrayOfObjects(ctx->columnExpr()); }

  VISIT(ColumnExprTernaryOp) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString("if");
    json.addKey("args");
    json.startArray();
    json.addRawJSON(visitAsJSON(ctx->columnExpr(0)));
    json.addRawJSON(visitAsJSON(ctx->columnExpr(1)));
    json.addRawJSON(visitAsJSON(ctx->columnExpr(2)));
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprAlias) {
    string alias;
    if (ctx->identifier()) {
      alias = visitAsString(ctx->identifier());
    } else if (ctx->STRING_LITERAL()) {
      alias = parse_string_literal_ctx(ctx->STRING_LITERAL());
    } else {
      throw ParsingError("A ColumnExprAlias must have the alias in some form");
    }

    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), boost::algorithm::to_lower_copy(alias)) !=
        RESERVED_KEYWORDS.end()) {
      throw SyntaxError("\"" + alias + "\" cannot be an alias or identifier, as it's a reserved keyword");
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Alias");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.addKey("alias");
    json.addString(alias);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprNegate) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArithmeticOperation");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    // Create a Constant 0 for left side
    JSONBuilder left_json;
    left_json.startObject();
    left_json.addNodeType("Constant");
    left_json.addKey("value");
    left_json.addInt(0);
    left_json.endObject();

    json.addKey("left");
    json.addRawJSON(left_json.toString());
    json.addKey("right");
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.addKey("op");
    json.addString("-");
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectSetStmt()); }

  VISIT(ColumnExprArray) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Array");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("exprs");
    json.addRawJSON(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprDict) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Dict");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("items");
    json.addRawJSON(visitAsJSONOrEmptyArray(ctx->kvPairList()));
    json.endObject();
    return json.toString();
  }

  VISIT_UNSUPPORTED(ColumnExprSubstring)

  VISIT_UNSUPPORTED(ColumnExprCast)

  VISIT(ColumnExprPrecedence1) {
    string op;
    if (ctx->SLASH()) {
      op = "/";
    } else if (ctx->ASTERISK()) {
      op = "*";
    } else if (ctx->PERCENT()) {
      op = "%";
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence1");
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArithmeticOperation");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("left");
    json.addRawJSON(visitAsJSON(ctx->columnExpr(0)));
    json.addKey("right");
    json.addRawJSON(visitAsJSON(ctx->right));
    json.addKey("op");
    json.addString(op);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprPrecedence2) {
    string left_json = visitAsJSON(ctx->left);
    string right_json = visitAsJSON(ctx->right);

    if (ctx->PLUS()) {
      JSONBuilder json;
      json.startObject();
      json.addNodeType("ArithmeticOperation");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("left");
      json.addRawJSON(left_json);
      json.addKey("right");
      json.addRawJSON(right_json);
      json.addKey("op");
      json.addString("+");
      json.endObject();
      return json.toString();
    } else if (ctx->DASH()) {
      JSONBuilder json;
      json.startObject();
      json.addNodeType("ArithmeticOperation");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("left");
      json.addRawJSON(left_json);
      json.addKey("right");
      json.addRawJSON(right_json);
      json.addKey("op");
      json.addString("-");
      json.endObject();
      return json.toString();
    } else if (ctx->CONCAT()) {
      // Check if left or right are already concat calls
      bool is_left_concat =
          left_json.find("\"node\":\"Call\"") != string::npos && left_json.find("\"name\":\"concat\"") != string::npos;
      bool is_right_concat = right_json.find("\"node\":\"Call\"") != string::npos &&
                             right_json.find("\"name\":\"concat\"") != string::npos;

      JSONBuilder json;
      json.startObject();
      json.addNodeType("Call");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("name");
      json.addString("concat");
      json.addKey("args");
      json.startArray();

      // Extract args from left if it's a concat, otherwise use left itself
      if (is_left_concat) {
        // Extract the args array from left_json
        size_t args_pos = left_json.find("\"args\":[");
        if (args_pos != string::npos) {
          size_t args_start = left_json.find('[', args_pos);
          int depth = 0;
          size_t i = args_start;
          for (; i < left_json.length(); i++) {
            if (left_json[i] == '[' || left_json[i] == '{')
              depth++;
            else if (left_json[i] == ']' || left_json[i] == '}') {
              depth--;
              if (depth == 0 && left_json[i] == ']') break;
            }
          }
          string args_content = left_json.substr(args_start + 1, i - args_start - 1);
          json.addRawJSON(args_content);
        }
      } else {
        json.addRawJSON(left_json);
      }

      // Extract args from right if it's a concat, otherwise use right itself
      if (is_right_concat) {
        size_t args_pos = right_json.find("\"args\":[");
        if (args_pos != string::npos) {
          size_t args_start = right_json.find('[', args_pos);
          int depth = 0;
          size_t i = args_start;
          for (; i < right_json.length(); i++) {
            if (right_json[i] == '[' || right_json[i] == '{')
              depth++;
            else if (right_json[i] == ']' || right_json[i] == '}') {
              depth--;
              if (depth == 0 && right_json[i] == ']') break;
            }
          }
          string args_content = right_json.substr(args_start + 1, i - args_start - 1);
          json.addRawJSON(args_content);
        }
      } else {
        json.addRawJSON(right_json);
      }

      json.endArray();
      json.endObject();
      return json.toString();
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence2");
    }
  }

  VISIT(ColumnExprPrecedence3) {
    string op;
    if (ctx->EQ_SINGLE() || ctx->EQ_DOUBLE()) {
      op = "==";
    } else if (ctx->NOT_EQ()) {
      op = "!=";
    } else if (ctx->LT()) {
      op = "<";
    } else if (ctx->LT_EQ()) {
      op = "<=";
    } else if (ctx->GT()) {
      op = ">";
    } else if (ctx->GT_EQ()) {
      op = ">=";
    } else if (ctx->LIKE()) {
      op = ctx->NOT() ? "not like" : "like";
    } else if (ctx->ILIKE()) {
      op = ctx->NOT() ? "not ilike" : "ilike";
    } else if (ctx->REGEX_SINGLE() or ctx->REGEX_DOUBLE()) {
      op = "=~";
    } else if (ctx->NOT_REGEX()) {
      op = "!~";
    } else if (ctx->IREGEX_SINGLE() or ctx->IREGEX_DOUBLE()) {
      op = "=~*";
    } else if (ctx->NOT_IREGEX()) {
      op = "!~*";
    } else if (ctx->IN()) {
      if (ctx->COHORT()) {
        op = ctx->NOT() ? "not in cohort" : "in cohort";
      } else {
        op = ctx->NOT() ? "not in" : "in";
      }
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence3");
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("CompareOperation");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("left");
    json.addRawJSON(visitAsJSON(ctx->left));
    json.addKey("right");
    json.addRawJSON(visitAsJSON(ctx->right));
    json.addKey("op");
    json.addString(op);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprInterval) {
    auto interval_ctx = ctx->interval();
    const char* name;
    if (interval_ctx->SECOND()) {
      name = "toIntervalSecond";
    } else if (interval_ctx->MINUTE()) {
      name = "toIntervalMinute";
    } else if (interval_ctx->HOUR()) {
      name = "toIntervalHour";
    } else if (interval_ctx->DAY()) {
      name = "toIntervalDay";
    } else if (interval_ctx->WEEK()) {
      name = "toIntervalWeek";
    } else if (interval_ctx->MONTH()) {
      name = "toIntervalMonth";
    } else if (interval_ctx->QUARTER()) {
      name = "toIntervalQuarter";
    } else if (interval_ctx->YEAR()) {
      name = "toIntervalYear";
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprInterval");
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("args");
    json.startArray();
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprIntervalString) {
    if (!ctx->STRING_LITERAL()) {
      throw NotImplementedError("Unsupported interval type: missing string literal");
    }

    // The text should contain something like "5 day", "2 weeks", etc.
    std::string text = parse_string_literal_ctx(ctx->STRING_LITERAL());

    auto space_pos = text.find(' ');
    if (space_pos == std::string::npos) {
      throw NotImplementedError("Unsupported interval type: must be in the format '<count> <unit>'");
    }
    std::string count_str = text.substr(0, space_pos);
    std::string unit_str = text.substr(space_pos + 1);

    for (char c : count_str) {
      if (!std::isdigit(static_cast<unsigned char>(c))) {
        throw NotImplementedError(("Unsupported interval count: " + count_str).c_str());
      }
    }
    int count_int = std::stoi(count_str);

    std::string name;
    if (unit_str == "second" || unit_str == "seconds") {
      name = "toIntervalSecond";
    } else if (unit_str == "minute" || unit_str == "minutes") {
      name = "toIntervalMinute";
    } else if (unit_str == "hour" || unit_str == "hours") {
      name = "toIntervalHour";
    } else if (unit_str == "day" || unit_str == "days") {
      name = "toIntervalDay";
    } else if (unit_str == "week" || unit_str == "weeks") {
      name = "toIntervalWeek";
    } else if (unit_str == "month" || unit_str == "months") {
      name = "toIntervalMonth";
    } else if (unit_str == "quarter" || unit_str == "quarters") {
      name = "toIntervalQuarter";
    } else if (unit_str == "year" || unit_str == "years") {
      name = "toIntervalYear";
    } else {
      throw NotImplementedError(("Unsupported interval unit: " + unit_str).c_str());
    }

    // Create Call with Constant argument
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("args");
    json.startArray();
    // Create inline Constant for the count
    JSONBuilder constant;
    constant.startObject();
    constant.addNodeType("Constant");
    constant.addKey("value");
    constant.addInt(count_int);
    constant.endObject();
    json.addRawJSON(constant.toString());
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprIsNull) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("CompareOperation");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("left");
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    // Create null constant for right side
    JSONBuilder null_constant;
    null_constant.startObject();
    null_constant.addNodeType("Constant");
    null_constant.addKey("value");
    null_constant.addNull();
    null_constant.endObject();
    json.addKey("right");
    json.addRawJSON(null_constant.toString());
    json.addKey("op");
    json.addString(ctx->NOT() ? "!=" : "==");
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprTrim) {
    const char* name;
    if (ctx->LEADING()) {
      name = "trimLeft";
    } else if (ctx->TRAILING()) {
      name = "trimRight";
    } else if (ctx->BOTH()) {
      name = "trim";
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprTrim");
    }
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("args");
    json.startArray();
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.addRawJSON(visitAsJSON(ctx->string()));
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprTuple) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Tuple");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("exprs");
    json.addRawJSON(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprArrayAccess) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArrayAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("array");
    json.addRawJSON(visitAsJSON(ctx->columnExpr(0)));
    json.addKey("property");
    json.addRawJSON(visitAsJSON(ctx->columnExpr(1)));
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprNullArrayAccess) {
    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArrayAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("array");
    json.addRawJSON(visitAsJSON(ctx->columnExpr(0)));
    json.addKey("property");
    json.addRawJSON(visitAsJSON(ctx->columnExpr(1)));
    json.addKey("nullish");
    json.addBool(true);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());
    // Create constant for property
    JSONBuilder property;
    property.startObject();
    property.addNodeType("Constant");
    property.addKey("value");
    property.addString(identifier);
    property.endObject();

    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArrayAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("array");
    json.addRawJSON(visitAsJSON(ctx->columnExpr()));
    json.addKey("property");
    json.addRawJSON(property.toString());
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprNullPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());

    // Build property Constant node
    JSONBuilder property_json;
    property_json.startObject();
    property_json.addNodeType("Constant");
    property_json.addKey("value");
    property_json.addString(identifier);
    property_json.endObject();

    string object_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("ArrayAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("array");
    json.addRawJSON(object_json);
    json.addKey("property");
    json.addRawJSON(property_json.toString());
    json.addKey("nullish");
    json.addBool(true);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprBetween) {
    string expr_json = visitAsJSON(ctx->columnExpr(0));
    string low_json = visitAsJSON(ctx->columnExpr(1));
    string high_json = visitAsJSON(ctx->columnExpr(2));

    JSONBuilder json;
    json.startObject();
    json.addNodeType("BetweenExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("low");
    json.addRawJSON(low_json);
    json.addKey("high");
    json.addRawJSON(high_json);
    json.addKey("negated");
    json.addBool(ctx->NOT() != nullptr);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprParens) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnExprTimestamp)

  VISIT(ColumnExprAnd) {
    string left_json = visitAsJSON(ctx->columnExpr(0));
    string right_json = visitAsJSON(ctx->columnExpr(1));

    // Check if left is an And node and extract its exprs
    vector<string> exprs;
    bool is_left_an_and = left_json.find("\"node\":\"And\"") != string::npos;
    if (is_left_an_and) {
      // Extract exprs array from left And node
      size_t exprs_pos = left_json.find("\"exprs\":[");
      if (exprs_pos != string::npos) {
        size_t start = exprs_pos + 9;  // after "exprs":[
        size_t end = left_json.find_last_of(']');
        string exprs_content = left_json.substr(start, end - start);
        if (!exprs_content.empty()) {
          // Parse individual expressions (simple brace counting)
          int depth = 0;
          size_t expr_start = 0;
          for (size_t i = 0; i < exprs_content.size(); i++) {
            if (exprs_content[i] == '{')
              depth++;
            else if (exprs_content[i] == '}')
              depth--;
            else if (exprs_content[i] == ',' && depth == 0) {
              exprs.push_back(exprs_content.substr(expr_start, i - expr_start));
              expr_start = i + 1;
            }
          }
          if (expr_start < exprs_content.size()) {
            exprs.push_back(exprs_content.substr(expr_start));
          }
        }
      }
    } else {
      exprs.push_back(left_json);
    }

    // Check if right is an And node and merge its exprs
    bool is_right_an_and = right_json.find("\"node\":\"And\"") != string::npos;
    if (is_right_an_and) {
      size_t exprs_pos = right_json.find("\"exprs\":[");
      if (exprs_pos != string::npos) {
        size_t start = exprs_pos + 9;
        size_t end = right_json.find_last_of(']');
        string exprs_content = right_json.substr(start, end - start);
        if (!exprs_content.empty()) {
          int depth = 0;
          size_t expr_start = 0;
          for (size_t i = 0; i < exprs_content.size(); i++) {
            if (exprs_content[i] == '{')
              depth++;
            else if (exprs_content[i] == '}')
              depth--;
            else if (exprs_content[i] == ',' && depth == 0) {
              exprs.push_back(exprs_content.substr(expr_start, i - expr_start));
              expr_start = i + 1;
            }
          }
          if (expr_start < exprs_content.size()) {
            exprs.push_back(exprs_content.substr(expr_start));
          }
        }
      }
    } else {
      exprs.push_back(right_json);
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("And");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("exprs");
    json.startArray();
    for (const auto& expr : exprs) {
      json.addRawJSON(expr);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprOr) {
    string left_json = visitAsJSON(ctx->columnExpr(0));
    string right_json = visitAsJSON(ctx->columnExpr(1));

    // Check if left is an Or node and extract its exprs
    vector<string> exprs;
    bool is_left_an_or = left_json.find("\"node\":\"Or\"") != string::npos;
    if (is_left_an_or) {
      // Extract exprs array from left Or node
      size_t exprs_pos = left_json.find("\"exprs\":[");
      if (exprs_pos != string::npos) {
        size_t start = exprs_pos + 9;  // after "exprs":[
        size_t end = left_json.find_last_of(']');
        string exprs_content = left_json.substr(start, end - start);
        if (!exprs_content.empty()) {
          // Parse individual expressions (simple brace counting)
          int depth = 0;
          size_t expr_start = 0;
          for (size_t i = 0; i < exprs_content.size(); i++) {
            if (exprs_content[i] == '{')
              depth++;
            else if (exprs_content[i] == '}')
              depth--;
            else if (exprs_content[i] == ',' && depth == 0) {
              exprs.push_back(exprs_content.substr(expr_start, i - expr_start));
              expr_start = i + 1;
            }
          }
          if (expr_start < exprs_content.size()) {
            exprs.push_back(exprs_content.substr(expr_start));
          }
        }
      }
    } else {
      exprs.push_back(left_json);
    }

    // Check if right is an Or node and merge its exprs
    bool is_right_an_or = right_json.find("\"node\":\"Or\"") != string::npos;
    if (is_right_an_or) {
      size_t exprs_pos = right_json.find("\"exprs\":[");
      if (exprs_pos != string::npos) {
        size_t start = exprs_pos + 9;
        size_t end = right_json.find_last_of(']');
        string exprs_content = right_json.substr(start, end - start);
        if (!exprs_content.empty()) {
          int depth = 0;
          size_t expr_start = 0;
          for (size_t i = 0; i < exprs_content.size(); i++) {
            if (exprs_content[i] == '{')
              depth++;
            else if (exprs_content[i] == '}')
              depth--;
            else if (exprs_content[i] == ',' && depth == 0) {
              exprs.push_back(exprs_content.substr(expr_start, i - expr_start));
              expr_start = i + 1;
            }
          }
          if (expr_start < exprs_content.size()) {
            exprs.push_back(exprs_content.substr(expr_start));
          }
        }
      }
    } else {
      exprs.push_back(right_json);
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Or");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("exprs");
    json.startArray();
    for (const auto& expr : exprs) {
      json.addRawJSON(expr);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    string tuple_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("TupleAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("tuple");
    json.addRawJSON(tuple_json);
    json.addKey("index");
    json.addInt(index_value);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprNullTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    string tuple_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("TupleAccess");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("tuple");
    json.addRawJSON(tuple_json);
    json.addKey("index");
    json.addInt(index_value);
    json.addKey("nullish");
    json.addBool(true);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprCase) {
    auto column_expr_ctx = ctx->columnExpr();
    size_t columns_size = column_expr_ctx.size();
    vector<string> columns = visitAsVectorOfJSON(column_expr_ctx);

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }

    if (ctx->caseExpr) {
      // CASE expr WHEN ... THEN ... ELSE ... END
      // Transform to: transform(expr, [conditions], [results], else_result)
      json.addKey("name");
      json.addString("transform");
      json.addKey("args");
      json.startArray();

      // arg_0: the case expression
      json.addRawJSON(columns[0]);

      // arg_1: Array of conditions (odd indices from 1 to columns_size-2)
      JSONBuilder conditions_array;
      conditions_array.startObject();
      conditions_array.addNodeType("Array");
      conditions_array.addKey("exprs");
      conditions_array.startArray();
      for (size_t index = 1; index < columns_size - 1; index++) {
        if ((index - 1) % 2 == 0) {
          conditions_array.addRawJSON(columns[index]);
        }
      }
      conditions_array.endArray();
      conditions_array.endObject();
      json.addRawJSON(conditions_array.toString());

      // arg_2: Array of results (even indices from 1 to columns_size-2)
      JSONBuilder results_array;
      results_array.startObject();
      results_array.addNodeType("Array");
      results_array.addKey("exprs");
      results_array.startArray();
      for (size_t index = 1; index < columns_size - 1; index++) {
        if ((index - 1) % 2 == 1) {
          results_array.addRawJSON(columns[index]);
        }
      }
      results_array.endArray();
      results_array.endObject();
      json.addRawJSON(results_array.toString());

      // arg_3: else result (last element)
      json.addRawJSON(columns[columns_size - 1]);

      json.endArray();
    } else {
      // CASE WHEN ... THEN ... ELSE ... END
      json.addKey("name");
      json.addString(columns_size == 3 ? "if" : "multiIf");
      json.addKey("args");
      json.startArray();
      for (const auto& col : columns) {
        json.addRawJSON(col);
      }
      json.endArray();
    }

    json.endObject();
    return json.toString();
  }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) {
    string expr_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Not");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprWinFunctionTarget) {
    auto column_expr_list_ctx = ctx->columnExprs;
    string name = visitAsString(ctx->identifier(0));
    string over_identifier = visitAsString(ctx->identifier(1));
    string exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    string args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);

    JSONBuilder json;
    json.startObject();
    json.addNodeType("WindowFunction");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("exprs");
    json.addRawJSON(exprs_json);
    json.addKey("args");
    json.addRawJSON(args_json);
    json.addKey("over_identifier");
    json.addString(over_identifier);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprWinFunction) {
    string identifier = visitAsString(ctx->identifier());
    auto column_expr_list_ctx = ctx->columnExprs;
    string exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    string args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);
    string over_expr_json = visitAsJSONOrNull(ctx->windowExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("WindowFunction");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(identifier);
    json.addKey("exprs");
    json.addRawJSON(exprs_json);
    json.addKey("args");
    json.addRawJSON(args_json);
    json.addKey("over_expr");
    json.addRawJSON(over_expr_json);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprIdentifier) { return visit(ctx->columnIdentifier()); }

  VISIT(ColumnExprFunction) {
    string name = visitAsString(ctx->identifier());

    // if two LPARENs ()(), make sure the first one is at least an empty list
    string params_json;
    if (ctx->LPAREN(1)) {
      params_json = visitAsJSONOrEmptyArray(ctx->columnExprs);
    } else {
      params_json = visitAsJSONOrNull(ctx->columnExprs);
    }

    string args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("params");
    json.addRawJSON(params_json);
    json.addKey("args");
    json.addRawJSON(args_json);
    json.addKey("distinct");
    json.addBool(ctx->DISTINCT() != nullptr);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprAsterisk) {
    auto table_identifier_ctx = ctx->tableIdentifier();

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Field");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("chain");
    json.startArray();

    if (table_identifier_ctx) {
      vector<string> table = any_cast<vector<string>>(visit(table_identifier_ctx));
      for (const auto& part : table) {
        json.addString(part);
      }
      json.addString("*");
    } else {
      json.addString("*");
    }

    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprTagElement) { return visit(ctx->hogqlxTagElement()); }

  VISIT(ColumnLambdaExpr) {
    auto column_expr_ctx = ctx->columnExpr();
    auto block_ctx = ctx->block();
    if (!column_expr_ctx && !block_ctx) {
      throw ParsingError("ColumnLambdaExpr must have either a columnExpr or a block");
    }

    string expr_json;
    if (column_expr_ctx) {
      expr_json = visitAsJSON(column_expr_ctx);
    } else {
      expr_json = visitAsJSON(block_ctx);
    }

    vector<string> args = visitAsVectorOfStrings(ctx->identifier());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Lambda");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("args");
    json.startArray();
    for (const auto& arg : args) {
      json.addString(arg);
    }
    json.endArray();
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.endObject();
    return json.toString();
  }

  VISIT(WithExprList) {
    // Build a JSON object (dictionary) mapping CTE names to CTE objects
    JSONBuilder json;
    json.startObject();

    for (auto with_expr_ctx : ctx->withExpr()) {
      string cte_json = visitAsJSON(with_expr_ctx);

      // Extract the "name" field from the CTE JSON to use as the key
      size_t name_pos = cte_json.find("\"name\":\"");
      if (name_pos != string::npos) {
        size_t name_start = name_pos + 8;  // after "name":"
        size_t name_end = cte_json.find("\"", name_start);
        string name = cte_json.substr(name_start, name_end - name_start);

        json.addKey(name);
        json.addRawJSON(cte_json);
      }
    }

    json.endObject();
    return json.toString();
  }

  VISIT(WithExprSubquery) {
    string name = visitAsString(ctx->identifier());
    string expr_json = visitAsJSON(ctx->selectSetStmt());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("CTE");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("cte_type");
    json.addString("subquery");
    json.endObject();
    return json.toString();
  }

  VISIT(WithExprColumn) {
    string name = visitAsString(ctx->identifier());
    string expr_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("CTE");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("cte_type");
    json.addString("column");
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnIdentifier) {
    auto placeholder_ctx = ctx->placeholder();
    if (placeholder_ctx) {
      return visitAsJSON(placeholder_ctx);
    }
    auto table_identifier_ctx = ctx->tableIdentifier();
    auto nested_identifier_ctx = ctx->nestedIdentifier();
    vector<string> table =
        table_identifier_ctx ? any_cast<vector<string>>(visit(table_identifier_ctx)) : vector<string>();
    vector<string> nested =
        nested_identifier_ctx ? any_cast<vector<string>>(visit(nested_identifier_ctx)) : vector<string>();

    if (table.size() == 0 && nested.size() > 0) {
      string text = ctx->getText();
      boost::algorithm::to_lower(text);
      if (!text.compare("true")) {
        JSONBuilder json;
        json.startObject();
        json.addNodeType("Constant");
        if (!is_internal) addPositionInfo(json, ctx);
        json.addKey("value");
        json.addBool(true);
        json.endObject();
        return json.toString();
      }
      if (!text.compare("false")) {
        JSONBuilder json;
        json.startObject();
        json.addNodeType("Constant");
        if (!is_internal) addPositionInfo(json, ctx);
        json.addKey("value");
        json.addBool(false);
        json.endObject();
        return json.toString();
      }
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Field");
      if (!is_internal) addPositionInfo(json, ctx);
      json.addKey("chain");
      json.startArray();
      for (const auto& part : nested) {
        json.addString(part);
      }
      json.endArray();
      json.endObject();
      return json.toString();
    }
    vector<string> table_plus_nested = table;
    table_plus_nested.insert(table_plus_nested.end(), nested.begin(), nested.end());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Field");
    if (!is_internal) addPositionInfo(json, ctx);
    json.addKey("chain");
    json.startArray();
    for (const auto& part : table_plus_nested) {
      json.addString(part);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(NestedIdentifier) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(TableExprIdentifier) {
    vector<string> chain = any_cast<vector<string>>(visit(ctx->tableIdentifier()));

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Field");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("chain");
    json.startArray();
    for (const auto& part : chain) {
      json.addString(part);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(TableExprSubquery) { return visit(ctx->selectSetStmt()); }

  VISIT(TableExprPlaceholder) { return visitAsJSON(ctx->placeholder()); }

  VISIT(TableExprAlias) {
    auto alias_ctx = ctx->alias();
    string alias = any_cast<string>(alias_ctx ? visit(alias_ctx) : visit(ctx->identifier()));
    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), boost::algorithm::to_lower_copy(alias)) !=
        RESERVED_KEYWORDS.end()) {
      throw SyntaxError("ALIAS is a reserved keyword");
    }

    string table_json = visitAsJSON(ctx->tableExpr());

    // Check if table is already a JoinExpr by looking at the START of the JSON
    bool is_table_a_join_expr = table_json.substr(0, 30).find("\"node\":\"JoinExpr\"") != string::npos;
    if (is_table_a_join_expr) {
      // Inject alias into existing JoinExpr before the closing brace
      size_t insert_pos = table_json.rfind("}");
      if (insert_pos != string::npos) {
        string alias_injection = ",\"alias\":\"" + JSONBuilder::escapeString(alias) + "\"";
        table_json.insert(insert_pos, alias_injection);
      }
      return table_json;
    }

    // Wrap table in a JoinExpr with alias
    // Note: sample/table_final/join_type/constraint will be injected by JoinExprTable/JoinExprOp before the final }
    JSONBuilder json;
    json.startObject();
    json.addNodeType("JoinExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("table");
    json.addRawJSON(table_json);
    json.addKey("alias");
    json.addString(alias);
    json.addKey("next_join");
    json.addNull();
    json.endObject();
    return json.toString();
  }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  VISIT(TableExprTag) { return visit(ctx->hogqlxTagElement()); }

  VISIT(TableFunctionExpr) {
    string table_name = visitAsString(ctx->identifier());
    auto table_args_ctx = ctx->tableArgList();
    string table_args_json = table_args_ctx ? visitAsJSON(table_args_ctx) : "[]";

    // Build Field node for table name
    JSONBuilder table_json;
    table_json.startObject();
    table_json.addNodeType("Field");
    table_json.addKey("chain");
    table_json.startArray();
    table_json.addString(table_name);
    table_json.endArray();
    table_json.endObject();

    // Build JoinExpr wrapping the table with table_args
    JSONBuilder json;
    json.startObject();
    json.addNodeType("JoinExpr");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("table");
    json.addRawJSON(table_json.toString());
    json.addKey("table_args");
    json.addRawJSON(table_args_json);
    json.endObject();
    return json.toString();
  }

  VISIT(TableIdentifier) {
    auto nested_identifier_ctx = ctx->nestedIdentifier();
    vector<string> nested =
        nested_identifier_ctx ? any_cast<vector<string>>(visit(nested_identifier_ctx)) : vector<string>();

    auto database_identifier_ctx = ctx->databaseIdentifier();
    if (database_identifier_ctx) {
      vector<string> database_plus_nested = vector<string>{visitAsString(database_identifier_ctx)};
      database_plus_nested.insert(database_plus_nested.end(), nested.begin(), nested.end());
      return database_plus_nested;
    }
    return nested;
  }

  VISIT(TableArgList) { return visitJSONArrayOfObjects(ctx->columnExpr()); }

  VISIT(DatabaseIdentifier) { return visit(ctx->identifier()); }

  VISIT_UNSUPPORTED(FloatingLiteral)

  VISIT(NumberLiteral) {
    string text = ctx->getText();
    boost::algorithm::to_lower(text);

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Constant");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("value");

    if (text.find(".") != string::npos || text.find("e") != string::npos || !text.compare("-inf") ||
        !text.compare("inf") || !text.compare("nan")) {
      // Float value
      double value = stod(text);
      json.addFloat(value);
    } else {
      // Integer value
      int64_t value = stoll(text);
      json.addInt(value);
    }

    json.endObject();
    return json.toString();
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("value");
      json.addNull();
      json.endObject();
      return json.toString();
    }
    auto string_literal_terminal = ctx->STRING_LITERAL();
    if (string_literal_terminal) {
      string text = parse_string_literal_ctx(string_literal_terminal);
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("value");
      json.addString(text);
      json.endObject();
      return json.toString();
    }
    return visitChildren(ctx);
  }

  VISIT_UNSUPPORTED(Interval)

  VISIT_UNSUPPORTED(Keyword)

  VISIT_UNSUPPORTED(KeywordForAlias)

  VISIT(Alias) {
    string text = ctx->getText();
    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), boost::algorithm::to_lower_copy(text)) !=
        RESERVED_KEYWORDS.end()) {
      throw SyntaxError("ALIAS is a reserved keyword");
    }
    return text;
  }

  VISIT(Identifier) {
    string text = ctx->getText();
    if (text.size() >= 2) {
      char first_char = text.front();
      char last_char = text.back();
      if ((first_char == '`' && last_char == '`') || (first_char == '"' && last_char == '"')) {
        return parse_string_literal_text(text);
      }
    }
    return text;
  }

  VISIT(HogqlxTagAttribute) {
    string name = visitAsString(ctx->identifier());

    string value_json;
    auto column_expr_ctx = ctx->columnExpr();
    if (column_expr_ctx) {
      value_json = visitAsJSON(column_expr_ctx);
    } else {
      auto string_ctx = ctx->string();
      if (string_ctx) {
        value_json = visitAsJSON(string_ctx);
      } else {
        // Default to true Constant
        JSONBuilder value_builder;
        value_builder.startObject();
        value_builder.addNodeType("Constant");
        value_builder.addKey("value");
        value_builder.addBool(true);
        value_builder.endObject();
        value_json = value_builder.toString();
      }
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("HogQLXAttribute");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString(name);
    json.addKey("value");
    json.addRawJSON(value_json);
    json.endObject();
    return json.toString();
  }

  VISIT(HogqlxChildElement) {
    auto tag_element_ctx = ctx->hogqlxTagElement();
    if (tag_element_ctx) {
      return visitAsJSON(tag_element_ctx);
    }
    auto text_element_ctx = ctx->hogqlxText();
    if (text_element_ctx) {
      return visitAsJSON(text_element_ctx);
    }
    return visitAsJSON(ctx->columnExpr());
  }

  VISIT(HogqlxText) {
    string text = ctx->HOGQLX_TEXT_TEXT()->getText();

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Constant");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("value");
    json.addString(text);
    json.endObject();
    return json.toString();
  }

  VISIT(HogqlxTagElementClosed) {
    string kind = visitAsString(ctx->identifier());
    vector<string> attributes = visitAsVectorOfJSON(ctx->hogqlxTagAttribute());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("HogQLXTag");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("kind");
    json.addString(kind);
    json.addKey("attributes");
    json.startArray();
    for (const auto& attr : attributes) {
      json.addRawJSON(attr);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(HogqlxTagElementNested) {
    std::string opening = visitAsString(ctx->identifier(0));
    std::string closing = visitAsString(ctx->identifier(1));
    if (opening != closing) {
      throw SyntaxError("Opening and closing HogQLX tags must match. Got " + opening + " and " + closing);
    }

    auto attribute_ctxs = ctx->hogqlxTagAttribute();
    vector<string> attributes = visitAsVectorOfJSON(attribute_ctxs);

    /* ── children ───────────────────────────────────────────── */
    std::vector<string> kept_children;
    for (auto childCtx : ctx->hogqlxChildElement()) {
      string child_json = visitAsJSON(childCtx);

      /* drop Constant nodes that are only-whitespace *and* contain a line-break */
      bool is_const = child_json.find("\"node\":\"Constant\"") != string::npos;
      if (is_const) {
        // Extract value from JSON
        size_t value_pos = child_json.find("\"value\":\"");
        if (value_pos != string::npos) {
          size_t value_start = value_pos + 9;  // after "value":"
          size_t value_end = child_json.find("\"", value_start);
          if (value_end != string::npos) {
            string value_text = child_json.substr(value_start, value_end - value_start);
            // Unescape the string to check for whitespace
            bool only_ws = std::all_of(value_text.begin(), value_text.end(), [](unsigned char c) {
              return std::isspace(c) || c == '\\';
            });
            bool has_newline = value_text.find("\\n") != std::string::npos ||
                               value_text.find("\\r") != std::string::npos ||
                               value_text.find('\n') != std::string::npos || value_text.find('\r') != std::string::npos;
            if (only_ws && has_newline) {
              continue;  // skip it
            }
          }
        }
      }

      kept_children.push_back(child_json);  // keep
    }

    /* if we have child nodes, validate + attach them as attribute "children" */
    if (!kept_children.empty()) {
      // Check if any attribute is named "children"
      for (const auto& attr_json : attributes) {
        if (attr_json.find("\"name\":\"children\"") != string::npos) {
          throw SyntaxError("Can't have a HogQLX tag with both children and a 'children' attribute");
        }
      }

      /* build children attribute */
      JSONBuilder children_array;
      children_array.startArray();
      for (const auto& child : kept_children) {
        children_array.addRawJSON(child);
      }
      children_array.endArray();

      JSONBuilder children_attr;
      children_attr.startObject();
      children_attr.addNodeType("HogQLXAttribute");
      children_attr.addKey("name");
      children_attr.addString("children");
      children_attr.addKey("value");
      children_attr.addRawJSON(children_array.toString());
      children_attr.endObject();

      attributes.push_back(children_attr.toString());
    }

    JSONBuilder json;
    json.startObject();
    json.addNodeType("HogQLXTag");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("kind");
    json.addString(opening);
    json.addKey("attributes");
    json.startArray();
    for (const auto& attr : attributes) {
      json.addRawJSON(attr);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(Placeholder) {
    string expr_json = visitAsJSON(ctx->columnExpr());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Placeholder");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.endObject();
    return json.toString();
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    string value_json = visitAsJSON(ctx->columnExpr(0));
    string fallback_json = visitAsJSON(ctx->columnExpr(1));

    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("name");
    json.addString("ifNull");
    json.addKey("args");
    json.startArray();
    json.addRawJSON(value_json);
    json.addRawJSON(fallback_json);
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprCall) {
    string expr_json = visitAsJSON(ctx->columnExpr());
    string args_json = visitAsJSONOrEmptyArray(ctx->columnExprList());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("ExprCall");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("args");
    json.addRawJSON(args_json);
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprCallSelect) {
    // 1) Parse the "function expression" from columnExpr().
    string expr_json = visitAsJSON(ctx->columnExpr());

    // 2) Check if `expr` is a Field node with a chain of length == 1.
    //    If so, interpret that chain[0] as the function name, and the SELECT as the function argument.
    bool is_field = expr_json.find("\"node\":\"Field\"") != string::npos;

    if (is_field) {
      // Extract chain array from Field
      size_t chain_pos = expr_json.find("\"chain\":[");
      if (chain_pos != string::npos) {
        size_t chain_start = chain_pos + 9;  // after "chain":[
        size_t chain_end = expr_json.find("]", chain_start);
        string chain_content = expr_json.substr(chain_start, chain_end - chain_start);

        // Check if chain has exactly one string element
        if (chain_content.find("\"") != string::npos &&
            chain_content.find("\",\"") == string::npos) {  // single element

          // Extract function name
          size_t name_start = chain_content.find("\"") + 1;
          size_t name_end = chain_content.find("\"", name_start);
          string func_name = chain_content.substr(name_start, name_end - name_start);

          // Build Call(name=func_name, args=[select])
          string select_json = visitAsJSON(ctx->selectSetStmt());

          JSONBuilder json;
          json.startObject();
          json.addNodeType("Call");
          if (!is_internal) {
            addPositionInfo(json, ctx);
          }
          json.addKey("name");
          json.addString(func_name);
          json.addKey("args");
          json.startArray();
          json.addRawJSON(select_json);
          json.endArray();
          json.endObject();
          return json.toString();
        }
      }
    }

    // 3) Otherwise, build ExprCall(expr=<expr>, args=[select])
    string select_json = visitAsJSON(ctx->selectSetStmt());

    JSONBuilder json;
    json.startObject();
    json.addNodeType("ExprCall");
    if (!is_internal) {
      addPositionInfo(json, ctx);
    }
    json.addKey("expr");
    json.addRawJSON(expr_json);
    json.addKey("args");
    json.startArray();
    json.addRawJSON(select_json);
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(ColumnExprTemplateString) { return visit(ctx->templateString()); }

  VISIT(String) {
    auto string_literal = ctx->STRING_LITERAL();
    if (string_literal) {
      string text = parse_string_literal_ctx(string_literal);
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json.addKey("value");
      json.addString(text);
      json.endObject();
      return json.toString();
    }
    return visit(ctx->templateString());
  }

  VISIT(TemplateString) {
    auto string_contents = ctx->stringContents();

    if (string_contents.size() == 0) {
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) addPositionInfo(json, ctx);
      json.addKey("value");
      json.addString("");
      json.endObject();
      return json.toString();
    }

    if (string_contents.size() == 1) {
      return visit(string_contents[0]);
    }

    vector<string> args = visitAsVectorOfJSON(string_contents);
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) addPositionInfo(json, ctx);
    json.addKey("name");
    json.addString("concat");
    json.addKey("args");
    json.startArray();
    for (const auto& arg : args) {
      json.addRawJSON(arg);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(FullTemplateString) {
    auto string_contents_full = ctx->stringContentsFull();

    if (string_contents_full.size() == 0) {
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) addPositionInfo(json, ctx);
      json.addKey("value");
      json.addString("");
      json.endObject();
      return json.toString();
    }

    if (string_contents_full.size() == 1) {
      return visit(string_contents_full[0]);
    }

    vector<string> args = visitAsVectorOfJSON(string_contents_full);
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Call");
    if (!is_internal) addPositionInfo(json, ctx);
    json.addKey("name");
    json.addString("concat");
    json.addKey("args");
    json.startArray();
    for (const auto& arg : args) {
      json.addRawJSON(arg);
    }
    json.endArray();
    json.endObject();
    return json.toString();
  }

  VISIT(StringContents) {
    auto string_text = ctx->STRING_TEXT();
    if (string_text) {
      string text = parse_string_text_ctx(string_text, true);
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) addPositionInfo(json, ctx);
      json.addKey("value");
      json.addString(text);
      json.endObject();
      return json.toString();
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Constant");
    if (!is_internal) addPositionInfo(json, ctx);
    json.addKey("value");
    json.addString("");
    json.endObject();
    return json.toString();
  }

  VISIT(StringContentsFull) {
    auto full_string_text = ctx->FULL_STRING_TEXT();
    if (full_string_text) {
      string text = parse_string_text_ctx(full_string_text, false);
      JSONBuilder json;
      json.startObject();
      json.addNodeType("Constant");
      if (!is_internal) addPositionInfo(json, ctx);
      json.addKey("value");
      json.addString(text);
      json.endObject();
      return json.toString();
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    JSONBuilder json;
    json.startObject();
    json.addNodeType("Constant");
    if (!is_internal) addPositionInfo(json, ctx);
    json.addKey("value");
    json.addString("");
    json.endObject();
    return json.toString();
  }
};
