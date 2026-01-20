// parser_json.cpp - Pure C++ HogQL Parser Core
// This file contains the core parser logic that returns JSON representations of ASTs.
// It can be compiled for Python (via parser_python.cpp), WebAssembly, or other platforms.

#include <boost/algorithm/string.hpp>
#include <sstream>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "json.h"
#include "string.h"

#define VISIT(RULE) any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                            \
  VISIT(RULE) {                                            \
    throw NotImplementedError("Unsupported rule: " #RULE); \
  }

using namespace std;

// JSON UTILS

// Helper: Add position information to Json object from ParserRuleContext
void addPositionInfo(Json& json, antlr4::ParserRuleContext* ctx) {
  if (!ctx) return;

  auto start_token = ctx->getStart();
  auto stop_token = ctx->getStop();

  if (start_token) {
    Json start = Json::object();
    start["line"] = static_cast<int64_t>(start_token->getLine());
    start["column"] = static_cast<int64_t>(start_token->getCharPositionInLine());
    start["offset"] = static_cast<int64_t>(start_token->getStartIndex());
    json["start"] = std::move(start);
  }

  if (stop_token) {
    Json end = Json::object();
    end["line"] = static_cast<int64_t>(stop_token->getLine());
    end["column"] = static_cast<int64_t>(stop_token->getCharPositionInLine() + stop_token->getText().length());
    end["offset"] = static_cast<int64_t>(stop_token->getStopIndex() + 1);
    json["end"] = std::move(end);
  }
}

// Helper: Add position from single token
void addPositionInfo(Json& json, const string& key, antlr4::Token* token) {
  if (!token) return;

  Json pos = Json::object();
  pos["line"] = static_cast<int64_t>(token->getLine());
  pos["column"] = static_cast<int64_t>(token->getCharPositionInLine());
  pos["offset"] = static_cast<int64_t>(token->getStartIndex());
  json[key] = std::move(pos);
}

// Helper: Add end position from single token
void addEndPositionInfo(Json& json, antlr4::Token* token) {
  if (!token) return;

  Json end = Json::object();
  end["line"] = static_cast<int64_t>(token->getLine());
  end["column"] = static_cast<int64_t>(token->getCharPositionInLine() + token->getText().length());
  end["offset"] = static_cast<int64_t>(token->getStopIndex() + 1);
  json["end"] = std::move(end);
}

// Helper: Build a JSON error object
Json buildJSONError(const char* errorType, const string& message, size_t start, size_t end) {
  Json json = Json::object();
  json["error"] = true;
  json["type"] = errorType;
  json["message"] = message;

  Json start_pos = Json::object();
  start_pos["line"] = 0;
  start_pos["column"] = 0;
  start_pos["offset"] = static_cast<int64_t>(start);
  json["start"] = std::move(start_pos);

  Json end_pos = Json::object();
  end_pos["line"] = 0;
  end_pos["column"] = 0;
  end_pos["offset"] = static_cast<int64_t>(end);
  json["end"] = std::move(end_pos);

  return json;
}

bool isNodeOfType(const Json& json, const string& type) {
  if (!json.isObject()) return false;
  auto obj = json.getObject();
  auto it = obj.find("node");
  if (it == obj.end()) return false;
  return it->second.getString() == type;
}

bool containsMatchingProperty(const Json& json, const string& prop_name, const string& prop_value) {
  if (!json.isObject()) return false;
  const auto& obj = json.getObject();
  auto it = obj.find(prop_name);
  if (it != obj.end() && it->second.isString() && it->second.getString() == prop_value) {
    return true;
  }
  return false;
}

// PARSING AND AST CONVERSION

class HogQLParseTreeJSONConverter : public HogQLParserBaseVisitor {
 private:
  bool is_internal;

  const vector<string> RESERVED_KEYWORDS = {"true", "false", "null", "team_id"};

 public:
  HogQLParseTreeJSONConverter(bool is_internal) : is_internal(is_internal) {}

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
      return visitAsJSON(tree).dump();
    } catch (const SyntaxError& e) {
      return buildJSONError("SyntaxError", e.what(), e.start, e.end).dump();
    } catch (const NotImplementedError& e) {
      return buildJSONError("NotImplementedError", e.what(), e.start, e.end).dump();
    } catch (const ParsingError& e) {
      return buildJSONError("ParsingError", e.what(), e.start, e.end).dump();
    } catch (const bad_any_cast& e) {
      return buildJSONError("ParsingError", "Parsing failed due to bad type casting", 0, 0).dump();
    } catch (...) {
      return buildJSONError("ParsingError", "Unknown parsing error occurred", 0, 0).dump();
    }
  }

  // JSON helper methods
  Json visitAsJSON(antlr4::tree::ParseTree* tree) {
    if (!tree) {
      return Json(nullptr);
    }
    return any_cast<Json>(visit(tree));
  }

  Json visitAsJSONOrNull(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      return Json(nullptr);
    }
    try {
      return visitAsJSON(tree);
    } catch (const bad_any_cast& e) {
      cout << tree->toStringTree(true) << endl;
      throw ParsingError("Failed to cast parse tree node to JSON");
    }
  }

  Json visitAsJSONOrEmptyArray(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      return Json::array();
    }
    return visitAsJSON(tree);
  }

  template <typename T>
  Json visitJSONArrayOfObjects(vector<T> trees) {
    Json result = Json::array();
    for (auto tree : trees) {
      result.pushBack(visitAsJSON(tree));
    }
    return result;
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
  vector<Json> visitAsVectorOfJSON(vector<T> trees) {
    vector<Json> ret;
    ret.reserve(trees.size());
    for (auto tree : trees) {
      ret.push_back(visitAsJSON(tree));
    }
    return ret;
  }

  VISIT(Program) {
    Json json = Json::object();
    json["node"] = "Program";
    if (!is_internal) addPositionInfo(json, ctx);
    Json declarations = Json::array();
    const auto declaration_ctxs = ctx->declaration();
    for (const auto declaration_ctx : declaration_ctxs) {
      if (declaration_ctx->statement() && declaration_ctx->statement()->emptyStmt()) {
        continue;
      }
      declarations.pushBack(visitAsJSON(declaration_ctx));
    }
    json["declarations"] = std::move(declarations);
    return json;
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
    Json json = Json::object();
    if (!is_internal) addPositionInfo(json, ctx);
    json["node"] = "VariableDeclaration";
    json["name"] = visitAsString(ctx->identifier());
    json["expr"] = visitAsJSONOrNull(ctx->expression());
    return json;
  }

  VISIT(VarAssignment) {
    Json json = Json::object();
    json["node"] = "VariableAssignment";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = visitAsJSON(ctx->expression(0));
    json["right"] = visitAsJSON(ctx->expression(1));
    return json;
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
    Json json = Json::object();
    json["node"] = "ExprStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->expression());
    return json;
  }

  VISIT(ReturnStmt) {
    Json json = Json::object();
    json["node"] = "ReturnStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSONOrNull(ctx->expression());
    return json;
  }

  VISIT(ThrowStmt) {
    Json json = Json::object();
    json["node"] = "ThrowStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSONOrNull(ctx->expression());
    return json;
  }

  VISIT(CatchBlock) {
    // CatchBlock returns an array [catchVar, catchType, catchStmt]
    Json arr = Json::array();
    if (ctx->catchVar) {
      arr.pushBack(visitAsString(ctx->catchVar));
    } else {
      arr.pushBack(nullptr);
    }
    if (ctx->catchType) {
      arr.pushBack(visitAsString(ctx->catchType));
    } else {
      arr.pushBack(nullptr);
    }
    arr.pushBack(visitAsJSON(ctx->catchStmt));
    return arr;
  }

  VISIT(TryCatchStmt) {
    Json json = Json::object();
    json["node"] = "TryCatchStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["try_stmt"] = visitAsJSON(ctx->tryStmt);
    Json catches = Json::array();
    const auto catch_block_ctxs = ctx->catchBlock();
    for (const auto catch_block_ctx : catch_block_ctxs) {
      catches.pushBack(visitAsJSON(catch_block_ctx));
    }
    json["catches"] = std::move(catches);
    json["finally_stmt"] = visitAsJSONOrNull(ctx->finallyStmt);
    return json;
  }

  VISIT(IfStmt) {
    Json json = Json::object();
    json["node"] = "IfStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->expression());
    json["then"] = visitAsJSON(ctx->statement(0));
    json["else_"] = visitAsJSONOrNull(ctx->statement(1));
    return json;
  }

  VISIT(WhileStmt) {
    Json json = Json::object();
    json["node"] = "WhileStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->expression());
    json["body"] = visitAsJSONOrNull(ctx->statement());
    return json;
  }

  VISIT(ForStmt) {
    Json json = Json::object();
    json["node"] = "ForStatement";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->initializerVarDeclr) {
      json["initializer"] = visitAsJSON(ctx->initializerVarDeclr);
    } else if (ctx->initializerVarAssignment) {
      json["initializer"] = visitAsJSON(ctx->initializerVarAssignment);
    } else if (ctx->initializerExpression) {
      json["initializer"] = visitAsJSON(ctx->initializerExpression);
    } else {
      json["initializer"] = nullptr;
    }

    json["condition"] = visitAsJSONOrNull(ctx->condition);

    if (ctx->incrementVarDeclr) {
      json["increment"] = visitAsJSON(ctx->incrementVarDeclr);
    } else if (ctx->incrementVarAssignment) {
      json["increment"] = visitAsJSON(ctx->incrementVarAssignment);
    } else if (ctx->incrementExpression) {
      json["increment"] = visitAsJSON(ctx->incrementExpression);
    } else {
      json["increment"] = nullptr;
    }

    json["body"] = visitAsJSON(ctx->statement());
    return json;
  }

  VISIT(ForInStmt) {
    Json json = Json::object();
    json["node"] = "ForInStatement";
    if (!is_internal) addPositionInfo(json, ctx);

    string firstIdentifier = visitAsString(ctx->identifier(0));
    if (ctx->identifier(1)) {
      string secondIdentifier = visitAsString(ctx->identifier(1));
      json["keyVar"] = firstIdentifier;
      json["valueVar"] = secondIdentifier;
    } else {
      json["keyVar"] = nullptr;
      json["valueVar"] = firstIdentifier;
    }

    json["expr"] = visitAsJSON(ctx->expression());
    json["body"] = visitAsJSON(ctx->statement());
    return json;
  }

  VISIT(FuncStmt) {
    Json json = Json::object();
    json["node"] = "Function";
    if (!is_internal) addPositionInfo(json, ctx);

    json["name"] = visitAsString(ctx->identifier());

    Json params = Json::array();
    const auto identifier_list_ctx = ctx->identifierList();
    if (identifier_list_ctx) {
      vector<string> paramList = any_cast<vector<string>>(visit(identifier_list_ctx));
      for (const auto& param : paramList) {
        params.pushBack(param);
      }
    }
    json["params"] = std::move(params);

    json["body"] = visitAsJSON(ctx->block());
    return json;
  }

  VISIT(KvPairList) {
    Json arr = Json::array();
    for (const auto kv_pair_ctx : ctx->kvPair()) {
      arr.pushBack(visitAsJSON(kv_pair_ctx));
    }
    return arr;
  }

  VISIT(KvPair) {
    // KvPair returns an array [key, value]
    Json arr = Json::array();
    arr.pushBack(visitAsJSON(ctx->expression(0)));
    arr.pushBack(visitAsJSON(ctx->expression(1)));
    return arr;
  }

  VISIT(IdentifierList) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(EmptyStmt) {
    Json json = Json::object();
    json["node"] = "ExprStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = nullptr;
    return json;
  }

  VISIT(Block) {
    Json json = Json::object();
    json["node"] = "Block";
    if (!is_internal) addPositionInfo(json, ctx);
    Json declarations = Json::array();
    const auto declaration_ctxs = ctx->declaration();
    for (const auto declaration_ctx : declaration_ctxs) {
      if (!declaration_ctx->statement() || !declaration_ctx->statement()->emptyStmt()) {
        declarations.pushBack(visitAsJSON(declaration_ctx));
      }
    }
    json["declarations"] = std::move(declarations);
    return json;
  }

  // HogQL rules

  VISIT(Select) {
    if (const auto select_set_stmt_ctx = ctx->selectSetStmt()) {
      return visit(select_set_stmt_ctx);
    }

    if (const auto select_stmt_ctx = ctx->selectStmt()) {
      return visit(select_stmt_ctx);
    }

    return visit(ctx->hogqlxTagElement());
  }

  VISIT(SelectStmtWithParens) {
    if (const auto select_stmt_ctx = ctx->selectStmt()) {
      return visit(select_stmt_ctx);
    }

    if (const auto placeholder_ctx = ctx->placeholder()) {
      return visit(placeholder_ctx);
    }

    return visit(ctx->selectSetStmt());
  }

  VISIT(SelectSetStmt) {
    const auto subsequent_clauses = ctx->subsequentSelectSetClause();

    if (subsequent_clauses.empty()) {
      return visit(ctx->selectStmtWithParens());
    }

    Json json = Json::object();
    json["node"] = "SelectSetQuery";
    if (!is_internal) addPositionInfo(json, ctx);

    json["initial_select_query"] = visitAsJSON(ctx->selectStmtWithParens());

    json["subsequent_select_queries"] = Json::array();
    for (const auto subsequent : subsequent_clauses) {
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

      Json node_json = Json::object();
      node_json["node"] = "SelectSetNode";
      node_json["select_query"] = visitAsJSON(subsequent->selectStmtWithParens());
      node_json["set_operator"] = set_operator;
      json["subsequent_select_queries"].pushBack(node_json);
    }

    return json;
  }

  VISIT(SelectStmt) {
    Json json = Json::object();
    json["node"] = "SelectQuery";
    if (!is_internal) addPositionInfo(json, ctx);

    // Add basic query fields
    json["ctes"] = visitAsJSONOrNull(ctx->withClause());
    json["select"] = visitAsJSONOrEmptyArray(ctx->columnExprList());
    json["distinct"] = ctx->DISTINCT() ? Json(true) : Json(nullptr);
    json["select_from"] = visitAsJSONOrNull(ctx->fromClause());
    json["where"] = visitAsJSONOrNull(ctx->whereClause());
    json["prewhere"] = visitAsJSONOrNull(ctx->prewhereClause());
    json["having"] = visitAsJSONOrNull(ctx->havingClause());
    json["group_by"] = visitAsJSONOrNull(ctx->groupByClause());
    json["order_by"] = visitAsJSONOrNull(ctx->orderByClause());

    // Handle window clause
    if (const auto window_clause_ctx = ctx->windowClause()) {
      const auto window_expr_ctxs = window_clause_ctx->windowExpr();
      const auto identifier_ctxs = window_clause_ctx->identifier();
      if (window_expr_ctxs.size() != identifier_ctxs.size()) {
        throw ParsingError("WindowClause must have a matching number of window exprs and identifiers");
      }
      json["window_exprs"] = Json::object();
      for (size_t i = 0; i < window_expr_ctxs.size(); i++) {
        string identifier = visitAsString(identifier_ctxs[i]);
        json["window_exprs"][identifier] = visitAsJSON(window_expr_ctxs[i]);
      }
    }

    // Handle offset and limit clauses
    const auto limit_and_offset_clause_ctx = ctx->limitAndOffsetClause();
    const auto offset_only_clause_ctx = ctx->offsetOnlyClause();

    if (offset_only_clause_ctx && !limit_and_offset_clause_ctx) {
      json["offset"] = visitAsJSON(offset_only_clause_ctx);
    }

    if (limit_and_offset_clause_ctx) {
      json["limit"] = visitAsJSON(limit_and_offset_clause_ctx->columnExpr(0));

      if (const auto offset_ctx = limit_and_offset_clause_ctx->columnExpr(1)) {
        json["offset"] = visitAsJSON(offset_ctx);
      }

      if (limit_and_offset_clause_ctx->WITH() && limit_and_offset_clause_ctx->TIES()) {
        json["limit_with_ties"] = true;
      }
    }

    // Handle limit_by clause
    const auto limit_by_clause_ctx = ctx->limitByClause();
    if (limit_by_clause_ctx) {
      json["limit_by"] = visitAsJSON(limit_by_clause_ctx);
    }

    // Handle array_join clause
    if (const auto array_join_clause_ctx = ctx->arrayJoinClause()) {
      Json select_from_json = visitAsJSONOrNull(ctx->fromClause());
      if (select_from_json.isNull()) {
        throw SyntaxError("Using ARRAY JOIN without a FROM clause is not permitted");
      }

      if (array_join_clause_ctx->LEFT()) {
        json["array_join_op"] = "LEFT ARRAY JOIN";
      } else if (array_join_clause_ctx->INNER()) {
        json["array_join_op"] = "INNER ARRAY JOIN";
      } else {
        json["array_join_op"] = "ARRAY JOIN";
      }

      const auto array_join_arrays_ctx = array_join_clause_ctx->columnExprList();
      const auto array_join_exprs = array_join_arrays_ctx->columnExpr();

      // Validate that all array join expressions have aliases
      for (const auto& expr_ctx : array_join_exprs) {
        Json expr_json = visitAsJSON(expr_ctx);
        if (!isNodeOfType(expr_json, "Alias")) {
          auto relevant_column_expr_ctx = expr_ctx;
          throw SyntaxError(
              "ARRAY JOIN arrays must have an alias", relevant_column_expr_ctx->getStart()->getStartIndex(),
              relevant_column_expr_ctx->getStop()->getStopIndex() + 1
          );
        }
      }

      json["array_join_list"] = visitAsJSON(array_join_arrays_ctx);
    }

    // Check for unsupported clauses
    if (ctx->topClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.topClause()");
    }
    if (ctx->settingsClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.settingsClause()");
    }

    return json;
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
    Json limit_expr_result = visitAsJSON(ctx->limitExpr());
    Json exprs = visitAsJSON(ctx->columnExprList());

    Json json = Json::object();
    json["node"] = "LimitByExpr";
    if (!is_internal) addPositionInfo(json, ctx);

    // Check if limitExprResult is an array (contains both n and offsetValue)
    if (limit_expr_result.isArray()) {
      if (limit_expr_result.getArray().size() == 2) {
        json["n"] = limit_expr_result.getArray()[0];
        json["offset_value"] = limit_expr_result.getArray()[1];
      } else {
        throw ParsingError("Invalid array format from limitExpr, expected 2 elements");
      }
    } else {
      // It's a single value, use as n with null offsetValue
      json["n"] = limit_expr_result;
      json["offset_value"] = nullptr;
    }

    json["exprs"] = exprs;
    return json;
  }

  VISIT(LimitExpr) {
    Json first = visitAsJSON(ctx->columnExpr(0));

    // If no second expression, just return the first
    if (!ctx->columnExpr(1)) {
      return first;
    }

    // We have both limit and offset - return as a simple array
    Json second = visitAsJSON(ctx->columnExpr(1));

    Json arr = Json::array();
    if (ctx->COMMA()) {
      // For "LIMIT a, b" syntax: a is offset, b is limit
      arr.pushBack(second);  // offset
      arr.pushBack(first);   // limit
    } else {
      // For "LIMIT a OFFSET b" syntax: a is limit, b is offset
      arr.pushBack(first);   // limit
      arr.pushBack(second);  // offset
    }
    return arr;
  }

  VISIT(OffsetOnlyClause) { return visitAsJSON(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ProjectionOrderByClause)

  VISIT_UNSUPPORTED(LimitAndOffsetClause)  // We handle this directly in the SelectStmt visitor

  VISIT_UNSUPPORTED(SettingsClause)

  // Helper: Chain two JOIN expressions together by finding the end of join1's chain
  Json chainJoinExprs(Json join1, Json join2) {
    if (!join1.isObject() || !join2.isObject()) {
      throw ParsingError("Both arguments to chainJoinExprs must be JSON objects");
    }

    Json* current = &join1;
    int depth = 0;
    const int max_depth = 1000;  // Prevent infinite loops

    while (current->isObject()) {
      auto& obj = current->getObjectMut();
      auto it = obj.find("next_join");

      if (it == obj.end()) {
        // This should not happen for valid JoinExpr nodes from the parser
        throw ParsingError("JoinExpr is missing 'next_join' field");
      }

      if (it->second.isNull()) {
        it->second = std::move(join2);
        return join1;
      }

      if (!it->second.isObject()) {
        throw ParsingError("'next_join' field is not a JSON object");
      }

      current = &it->second;

      if (++depth > max_depth) {
        throw ParsingError("Maximum recursion depth exceeded during JOIN parsing");
      }
    }

    // This part should be unreachable if the input is a valid JoinExpr
    throw ParsingError("Invalid structure for join expression chaining");
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

    Json join2_json = visitAsJSON(ctx->joinExpr(1));
    join2_json["join_type"] = join_op;
    join2_json["constraint"] = visitAsJSON(ctx->joinConstraintClause());
    Json join1_json = visitAsJSON(ctx->joinExpr(0));
    return chainJoinExprs(join1_json, join2_json);
  }

  VISIT(JoinExprTable) {
    Json table_json = visitAsJSON(ctx->tableExpr());
    Json sample_json = visitAsJSONOrNull(ctx->sampleClause());
    bool table_final = ctx->FINAL();

    // Check if table is already a JoinExpr
    bool isTableJoinExpr = isNodeOfType(table_json, "JoinExpr");

    if (isTableJoinExpr) {
      table_json["sample"] = sample_json;
      table_json["table_final"] = table_final ? Json(true) : Json(nullptr);
      return table_json;
    } else {
      // Create a new JoinExpr wrapping the table
      // Note: joinType/constraint will be injected by JoinExprOp before the closing }
      Json json = Json::object();
      json["node"] = "JoinExpr";
      if (!is_internal) addPositionInfo(json, ctx);
      json["table"] = table_json;
      json["table_final"] = table_final ? Json(true) : Json(nullptr);
      json["sample"] = sample_json;
      json["next_join"] = nullptr;
      json["alias"] = nullptr;
      return json;
    }
  }

  VISIT(JoinExprParens) { return visit(ctx->joinExpr()); }

  VISIT(JoinExprCrossOp) {
    Json join2_json = visitAsJSON(ctx->joinExpr(1));
    Json join1_json = visitAsJSON(ctx->joinExpr(0));
    join2_json["join_type"] = "CROSS JOIN";
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
    Json column_expr_list_json = visitAsJSON(ctx->columnExprList());

    if (column_expr_list_json.isArray() && column_expr_list_json.getArray().size() > 1) {
      throw NotImplementedError("Unsupported: JOIN ... ON with multiple expressions");
    }

    // Extract the single expression from the array
    Json expr_json = column_expr_list_json.getArray().at(0);

    Json json = Json::object();
    json["node"] = "JoinConstraint";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = expr_json;
    json["constraint_type"] = ctx->USING() ? "USING" : "ON";
    return json;
  }

  VISIT(SampleClause) {
    Json json = Json::object();
    json["node"] = "SampleExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["sample_value"] = visitAsJSON(ctx->ratioExpr(0));
    json["offset_value"] = visitAsJSONOrNull(ctx->ratioExpr(1));
    return json;
  }

  VISIT(OrderExprList) { return visitJSONArrayOfObjects(ctx->orderExpr()); }

  VISIT(OrderExpr) {
    const char* order = ctx->DESC() || ctx->DESCENDING() ? "DESC" : "ASC";
    Json json = Json::object();
    json["node"] = "OrderExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->columnExpr());
    json["order"] = order;
    return json;
  }

  VISIT(RatioExpr) {
    if (const auto placeholder_ctx = ctx->placeholder()) {
      return visitAsJSON(placeholder_ctx);
    }

    const auto number_literal_ctxs = ctx->numberLiteral();

    if (number_literal_ctxs.size() > 2) {
      throw ParsingError("RatioExpr must have at most two number literals");
    } else if (number_literal_ctxs.size() == 0) {
      throw ParsingError("RatioExpr must have at least one number literal");
    }

    auto left_ctx = number_literal_ctxs[0];
    auto right_ctx = ctx->SLASH() && number_literal_ctxs.size() > 1 ? number_literal_ctxs[1] : NULL;

    Json json = Json::object();
    json["node"] = "RatioExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = visitAsJSON(left_ctx);
    json["right"] = visitAsJSONOrNull(right_ctx);
    return json;
  }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  VISIT(WindowExpr) {
    auto frame_ctx = ctx->winFrameClause();
    Json frame_json = visitAsJSONOrNull(frame_ctx);
    Json frame_start_json = Json(nullptr);
    Json frame_end_json = Json(nullptr);

    if (!frame_json.isNull()) {
      if (frame_json.isArray()) {
        const auto& frameArray = frame_json.getArray();
        if (frameArray.size() == 2) {
          frame_start_json = frameArray[0];
          frame_end_json = frameArray[1];
        } else {
          throw ParsingError("WindowExpr frame must be an array of size 2");
        }
      } else {
        frame_start_json = frame_json;
      }
    }

    const char* frame_method = nullptr;
    if (frame_ctx) {
      if (frame_ctx->RANGE()) {
        frame_method = "RANGE";
      } else if (frame_ctx->ROWS()) {
        frame_method = "ROWS";
      }
    }

    Json json = Json::object();
    json["node"] = "WindowExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["partition_by"] = visitAsJSONOrNull(ctx->winPartitionByClause());
    json["order_by"] = visitAsJSONOrNull(ctx->winOrderByClause());
    if (frame_method) {
      json["frame_method"] = frame_method;
    }
    json["frame_start"] = frame_start_json;
    json["frame_end"] = frame_end_json;
    return json;
  }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  VISIT(FrameBetween) {
    // Return an array with [start, end]
    Json arr = Json::array();
    arr.pushBack(visitAsJSON(ctx->winFrameBound(0)));
    arr.pushBack(visitAsJSON(ctx->winFrameBound(1)));
    return arr;
  }

  VISIT(WinFrameBound) {
    Json json = Json::object();
    json["node"] = "WindowFrameExpr";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->PRECEDING() || ctx->FOLLOWING()) {
      json["frame_type"] = ctx->PRECEDING() ? "PRECEDING" : "FOLLOWING";
      if (ctx->numberLiteral()) {
        Json constant_json = visitAsJSON(ctx->numberLiteral());
        if (constant_json.isObject() && constant_json.getObject().contains("value")) {
          json["frame_value"] = constant_json["value"];
        } else {
          json["frame_value"] = nullptr;
        }
      } else {
        json["frame_value"] = nullptr;
      }
    } else {
      json["frame_type"] = "CURRENT ROW";
    }

    return json;
  }

  VISIT(Expr) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnTypeExprSimple)

  VISIT_UNSUPPORTED(ColumnTypeExprNested)

  VISIT_UNSUPPORTED(ColumnTypeExprEnum)

  VISIT_UNSUPPORTED(ColumnTypeExprComplex)

  VISIT_UNSUPPORTED(ColumnTypeExprParam)

  VISIT(ColumnExprList) { return visitJSONArrayOfObjects(ctx->columnExpr()); }

  VISIT(ColumnExprTernaryOp) {
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "if";
    Json args = Json::array();
    args.pushBack(visitAsJSON(ctx->columnExpr(0)));
    args.pushBack(visitAsJSON(ctx->columnExpr(1)));
    args.pushBack(visitAsJSON(ctx->columnExpr(2)));
    json["args"] = std::move(args);
    return json;
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

    Json json = Json::object();
    json["node"] = "Alias";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->columnExpr());
    json["alias"] = alias;
    return json;
  }

  VISIT(ColumnExprNegate) {
    Json json = Json::object();
    json["node"] = "ArithmeticOperation";
    if (!is_internal) addPositionInfo(json, ctx);
    // Create a Constant 0 for left side
    Json left_json = Json::object();
    left_json["node"] = "Constant";
    left_json["value"] = 0;

    json["left"] = std::move(left_json);
    json["right"] = visitAsJSON(ctx->columnExpr());
    json["op"] = "-";
    return json;
  }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectSetStmt()); }

  VISIT(ColumnExprArray) {
    Json json = Json::object();
    json["node"] = "Array";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = visitAsJSONOrEmptyArray(ctx->columnExprList());
    return json;
  }

  VISIT(ColumnExprDict) {
    Json json = Json::object();
    json["node"] = "Dict";
    if (!is_internal) addPositionInfo(json, ctx);
    json["items"] = visitAsJSONOrEmptyArray(ctx->kvPairList());
    return json;
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

    Json json = Json::object();
    json["node"] = "ArithmeticOperation";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = visitAsJSON(ctx->columnExpr(0));
    json["right"] = visitAsJSON(ctx->right);
    json["op"] = op;
    return json;
  }

  VISIT(ColumnExprPrecedence2) {
    Json left_json = visitAsJSON(ctx->left);
    Json right_json = visitAsJSON(ctx->right);

    if (ctx->PLUS()) {
      Json json = Json::object();
      json["node"] = "ArithmeticOperation";
      if (!is_internal) addPositionInfo(json, ctx);
      json["left"] = left_json;
      json["right"] = right_json;
      json["op"] = "+";
      return json;
    } else if (ctx->DASH()) {
      Json json = Json::object();
      json["node"] = "ArithmeticOperation";
      if (!is_internal) addPositionInfo(json, ctx);
      json["left"] = left_json;
      json["right"] = right_json;
      json["op"] = "-";
      return json;
    } else if (ctx->CONCAT()) {
      // Check if left or right are already concat calls
      bool is_left_concat = isNodeOfType(left_json, "Call") && containsMatchingProperty(left_json, "name", "concat");
      bool is_right_concat = isNodeOfType(right_json, "Call") && containsMatchingProperty(right_json, "name", "concat");

      // Build args string manually for concat flattening
      Json args = Json::array();

      // Extract args from left if it's a concat, otherwise use left itself
      if (is_left_concat) {
        args = left_json["args"];
      } else {
        args.pushBack(left_json);
      }

      // Extract args from right if it's a concat, otherwise use right itself
      if (is_right_concat) {
        for (const auto& item : right_json["args"].getArray()) {
          args.pushBack(item);
        }
      } else {
        args.pushBack(right_json);
      }

      Json json = Json::object();
      json["node"] = "Call";
      if (!is_internal) addPositionInfo(json, ctx);
      json["name"] = "concat";
      json["args"] = std::move(args);
      return json;
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

    Json json = Json::object();
    json["node"] = "CompareOperation";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = visitAsJSON(ctx->left);
    json["right"] = visitAsJSON(ctx->right);
    json["op"] = op;
    return json;
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

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    Json args = Json::array();
    args.pushBack(visitAsJSON(ctx->columnExpr()));
    json["args"] = std::move(args);
    return json;
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
    int countInt = std::stoi(count_str);

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
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    Json constant = Json::object();
    constant["node"] = "Constant";
    constant["value"] = countInt;
    Json args = Json::array();
    args.pushBack(std::move(constant));
    json["args"] = std::move(args);
    return json;
  }

  VISIT(ColumnExprIsNull) {
    Json json = Json::object();
    json["node"] = "CompareOperation";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = visitAsJSON(ctx->columnExpr());
    // Create null constant for right side
    Json null_constant = Json::object();
    null_constant["node"] = "Constant";
    null_constant["value"] = nullptr;
    json["right"] = std::move(null_constant);
    json["op"] = ctx->NOT() ? "!=" : "==";
    return json;
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
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    Json args = Json::array();
    args.pushBack(visitAsJSON(ctx->columnExpr()));
    args.pushBack(visitAsJSON(ctx->string()));
    json["args"] = std::move(args);
    return json;
  }

  VISIT(ColumnExprTuple) {
    Json json = Json::object();
    json["node"] = "Tuple";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = visitAsJSONOrEmptyArray(ctx->columnExprList());
    return json;
  }

  VISIT(ColumnExprArrayAccess) {
    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = visitAsJSON(ctx->columnExpr(0));
    json["property"] = visitAsJSON(ctx->columnExpr(1));
    return json;
  }

  VISIT(ColumnExprNullArrayAccess) {
    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = visitAsJSON(ctx->columnExpr(0));
    json["property"] = visitAsJSON(ctx->columnExpr(1));
    json["nullish"] = true;
    return json;
  }

  VISIT(ColumnExprPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());
    // Create constant for property
    Json property = Json::object();
    property["node"] = "Constant";
    property["value"] = identifier;

    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = visitAsJSON(ctx->columnExpr());
    json["property"] = std::move(property);
    return json;
  }

  VISIT(ColumnExprNullPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());

    // Build property Constant node
    Json property_json = Json::object();
    property_json["node"] = "Constant";
    property_json["value"] = identifier;

    Json object_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = std::move(object_json);
    json["property"] = std::move(property_json);
    json["nullish"] = true;
    return json;
  }

  VISIT(ColumnExprBetween) {
    Json json = Json::object();
    json["node"] = "BetweenExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->columnExpr(0));
    json["low"] = visitAsJSON(ctx->columnExpr(1));
    json["high"] = visitAsJSON(ctx->columnExpr(2));
    json["negated"] = ctx->NOT() != nullptr;
    return json;
  }

  VISIT(ColumnExprParens) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnExprTimestamp)

  VISIT(ColumnExprAnd) {
    Json left_json = visitAsJSON(ctx->columnExpr(0));
    Json right_json = visitAsJSON(ctx->columnExpr(1));

    Json exprs = Json::array();
    if (isNodeOfType(left_json, "And")) {
      exprs = left_json["exprs"];
    } else {
      exprs.pushBack(left_json);
    }

    if (isNodeOfType(right_json, "And")) {
      for (const auto& item : right_json["exprs"].getArray()) {
        exprs.pushBack(item);
      }
    } else {
      exprs.pushBack(right_json);
    }

    Json json = Json::object();
    json["node"] = "And";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = exprs;
    return json;
  }

  VISIT(ColumnExprOr) {
    Json left_json = visitAsJSON(ctx->columnExpr(0));
    Json right_json = visitAsJSON(ctx->columnExpr(1));

    Json exprs = Json::array();
    if (isNodeOfType(left_json, "Or")) {
      exprs = left_json["exprs"];
    } else {
      exprs.pushBack(left_json);
    }

    if (isNodeOfType(right_json, "Or")) {
      for (const auto& item : right_json["exprs"].getArray()) {
        exprs.pushBack(item);
      }
    } else {
      exprs.pushBack(right_json);
    }

    Json json = Json::object();
    json["node"] = "Or";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = exprs;
    return json;
  }

  VISIT(ColumnExprTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    Json tuple_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "TupleAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["tuple"] = tuple_json;
    json["index"] = index_value;
    return json;
  }

  VISIT(ColumnExprNullTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    Json tuple_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "TupleAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["tuple"] = tuple_json;
    json["index"] = index_value;
    json["nullish"] = true;
    return json;
  }

  VISIT(ColumnExprCase) {
    auto column_expr_ctx = ctx->columnExpr();
    size_t columns_size = column_expr_ctx.size();
    vector<Json> columns = visitAsVectorOfJSON(column_expr_ctx);

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->caseExpr) {
      // CASE expr WHEN ... THEN ... ELSE ... END
      // Transform to: transform(expr, [conditions], [results], else_result)
      json["name"] = "transform";

      Json args = Json::array();

      // arg_0: the case expression
      args.pushBack(columns[0]);

      // arg_1: Array of conditions (odd indices from 1 to columns_size-2)
      Json conditions_array = Json::object();
      conditions_array["node"] = "Array";
      Json conditions_exprs = Json::array();
      for (size_t index = 1; index < columns_size - 1; index++) {
        if ((index - 1) % 2 == 0) {
          conditions_exprs.pushBack(columns[index]);
        }
      }
      conditions_array["exprs"] = std::move(conditions_exprs);
      args.pushBack(std::move(conditions_array));

      // arg_2: Array of results (even indices from 1 to columns_size-2)
      Json results_array = Json::object();
      results_array["node"] = "Array";
      Json results_exprs = Json::array();
      for (size_t index = 1; index < columns_size - 1; index++) {
        if ((index - 1) % 2 == 1) {
          results_exprs.pushBack(columns[index]);
        }
      }
      results_array["exprs"] = std::move(results_exprs);
      args.pushBack(std::move(results_array));

      // arg_3: else result (last element)
      args.pushBack(columns[columns_size - 1]);

      json["args"] = args;
    } else {
      // CASE WHEN ... THEN ... ELSE ... END
      json["name"] = columns_size == 3 ? "if" : "multiIf";
      Json args = Json::array();
      for (const auto& col : columns) {
        args.pushBack(col);
      }
      json["args"] = std::move(args);
    }

    return json;
  }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) {
    Json expr_json = visitAsJSON(ctx->columnExpr());
    Json json = Json::object();
    json["node"] = "Not";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = expr_json;
    return json;
  }

  VISIT(ColumnExprWinFunctionTarget) {
    auto column_expr_list_ctx = ctx->columnExprs;
    string name = visitAsString(ctx->identifier(0));
    string over_identifier = visitAsString(ctx->identifier(1));
    Json exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    Json args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);

    Json json = Json::object();
    json["node"] = "WindowFunction";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["exprs"] = exprs_json;
    json["args"] = args_json;
    json["over_identifier"] = over_identifier;
    return json;
  }

  VISIT(ColumnExprWinFunction) {
    string identifier = visitAsString(ctx->identifier());
    auto column_expr_list_ctx = ctx->columnExprs;
    Json exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    Json args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);
    Json over_expr_json = visitAsJSONOrNull(ctx->windowExpr());

    Json json = Json::object();
    json["node"] = "WindowFunction";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = identifier;
    json["exprs"] = exprs_json;
    json["args"] = args_json;
    json["over_expr"] = over_expr_json;
    return json;
  }

  VISIT(ColumnExprIdentifier) { return visit(ctx->columnIdentifier()); }

  VISIT(ColumnExprFunction) {
    string name = visitAsString(ctx->identifier());

    // if two LPARENs ()(), make sure the first one is at least an empty list
    Json params_json;
    if (ctx->LPAREN(1)) {
      params_json = visitAsJSONOrEmptyArray(ctx->columnExprs);
    } else {
      params_json = visitAsJSONOrNull(ctx->columnExprs);
    }

    Json args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["params"] = params_json;
    json["args"] = args_json;
    json["distinct"] = ctx->DISTINCT() != nullptr;
    return json;
  }

  VISIT(ColumnExprAsterisk) {
    auto table_identifier_ctx = ctx->tableIdentifier();

    Json json = Json::object();
    json["node"] = "Field";
    if (!is_internal) addPositionInfo(json, ctx);
    Json chain = Json::array();

    if (table_identifier_ctx) {
      vector<string> table = any_cast<vector<string>>(visit(table_identifier_ctx));
      for (const auto& part : table) {
        chain.pushBack(part);
      }
      chain.pushBack("*");
    } else {
      chain.pushBack("*");
    }

    json["chain"] = std::move(chain);
    return json;
  }

  VISIT(ColumnExprTagElement) { return visit(ctx->hogqlxTagElement()); }

  VISIT(ColumnLambdaExpr) {
    auto column_expr_ctx = ctx->columnExpr();
    auto block_ctx = ctx->block();
    if (!column_expr_ctx && !block_ctx) {
      throw ParsingError("ColumnLambdaExpr must have either a columnExpr or a block");
    }

    Json expr_json;
    if (column_expr_ctx) {
      expr_json = visitAsJSON(column_expr_ctx);
    } else {
      expr_json = visitAsJSON(block_ctx);
    }

    vector<string> args_vec = visitAsVectorOfStrings(ctx->identifier());

    Json json = Json::object();
    json["node"] = "Lambda";
    if (!is_internal) addPositionInfo(json, ctx);
    Json args = Json::array();
    for (const auto& arg : args_vec) {
      args.pushBack(arg);
    }
    json["args"] = std::move(args);
    json["expr"] = std::move(expr_json);
    return json;
  }

  VISIT(WithExprList) {
    // Build a JSON object (dictionary) mapping CTE names to CTE objects
    Json json = Json::object();

    for (auto with_expr_ctx : ctx->withExpr()) {
      Json cte_json = visitAsJSON(with_expr_ctx);
      auto name = cte_json.getObject().at("name").getString();
      json[name] = std::move(cte_json);
    }

    return json;
  }

  VISIT(WithExprSubquery) {
    Json json = Json::object();
    json["node"] = "CTE";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = visitAsString(ctx->identifier());
    json["expr"] = visitAsJSON(ctx->selectSetStmt());
    json["cte_type"] = "subquery";
    return json;
  }

  VISIT(WithExprColumn) {
    Json json = Json::object();
    json["node"] = "CTE";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = visitAsString(ctx->identifier());
    json["expr"] = visitAsJSON(ctx->columnExpr());
    json["cte_type"] = "column";
    return json;
  }

  VISIT(ColumnIdentifier) {
    if (const auto placeholder_ctx = ctx->placeholder()) {
      return visitAsJSON(placeholder_ctx);
    }
    const auto table_identifier_ctx = ctx->tableIdentifier();
    const auto nested_identifier_ctx = ctx->nestedIdentifier();
    vector<string> table =
        table_identifier_ctx ? any_cast<vector<string>>(visit(table_identifier_ctx)) : vector<string>();
    vector<string> nested =
        nested_identifier_ctx ? any_cast<vector<string>>(visit(nested_identifier_ctx)) : vector<string>();

    if (table.size() == 0 && nested.size() > 0) {
      string text = ctx->getText();
      boost::algorithm::to_lower(text);
      if (!text.compare("true")) {
        Json json = Json::object();
        json["node"] = "Constant";
        if (!is_internal) addPositionInfo(json, ctx);
        json["value"] = true;
        return json;
      }
      if (!text.compare("false")) {
        Json json = Json::object();
        json["node"] = "Constant";
        if (!is_internal) addPositionInfo(json, ctx);
        json["value"] = false;
        return json;
      }
      Json json = Json::object();
      json["node"] = "Field";
      if (!is_internal) addPositionInfo(json, ctx);
      Json chain = Json::array();
      for (const auto& part : nested) {
        chain.pushBack(part);
      }
      json["chain"] = std::move(chain);
      return json;
    }
    vector<string> table_plus_nested = table;
    table_plus_nested.insert(table_plus_nested.end(), nested.begin(), nested.end());

    Json json = Json::object();
    json["node"] = "Field";
    if (!is_internal) addPositionInfo(json, ctx);
    Json chain = Json::array();
    for (const auto& part : table_plus_nested) {
      chain.pushBack(part);
    }
    json["chain"] = std::move(chain);
    return json;
  }

  VISIT(NestedIdentifier) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(TableExprIdentifier) {
    vector<string> chain_vec = any_cast<vector<string>>(visit(ctx->tableIdentifier()));

    Json json = Json::object();
    json["node"] = "Field";
    if (!is_internal) addPositionInfo(json, ctx);
    Json chain = Json::array();
    for (const auto& part : chain_vec) {
      chain.pushBack(part);
    }
    json["chain"] = std::move(chain);
    return json;
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

    Json table_json = visitAsJSON(ctx->tableExpr());

    // Check if table is already a JoinExpr
    bool is_table_a_join_expr = isNodeOfType(table_json, "JoinExpr");
    if (is_table_a_join_expr) {
      // Inject alias into the existing JoinExpr
      table_json["alias"] = alias;
      return table_json;
    }

    // Wrap table in a JoinExpr with alias
    // Note: sample/table_final/join_type/constraint will be injected by JoinExprTable/JoinExprOp before the final }
    Json json = Json::object();
    json["node"] = "JoinExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["table"] = std::move(table_json);
    json["alias"] = alias;
    json["next_join"] = nullptr;
    return json;
  }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  VISIT(TableExprTag) { return visit(ctx->hogqlxTagElement()); }

  VISIT(TableFunctionExpr) {
    string table_name = visitAsString(ctx->identifier());
    auto table_args_ctx = ctx->tableArgList();
    Json table_args_json = table_args_ctx ? visitAsJSON(table_args_ctx) : Json::array();

    // Build Field node for table name
    Json table_json = Json::object();
    table_json["node"] = "Field";
    Json chain = Json::array();
    chain.pushBack(table_name);
    table_json["chain"] = std::move(chain);

    // Build JoinExpr wrapping the table with table_args
    Json json = Json::object();
    json["node"] = "JoinExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["table"] = std::move(table_json);
    json["table_args"] = std::move(table_args_json);
    return json;
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
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);

    string text = ctx->getText();
    boost::algorithm::to_lower(text);

    if (text.find("inf") != string::npos || text.find("nan") != string::npos) {
      // Handle special number cases (infinity and NaN)
      // Mark these with value_type="number" so the deserializer knows to convert them
      if (!text.compare("-inf")) {
        json["value"] = "-Infinity";
      } else if (!text.compare("inf")) {
        json["value"] = "Infinity";
      } else {
        json["value"] = "NaN";
      }
      json["value_type"] = "number";
    } else if (text.find(".") != string::npos || text.find("e") != string::npos) {
      json["value"] = Json(stod(text));  // Float
      return json;
    } else {
      json["value"] = static_cast<int64_t>(stoll(text));  // Integer
      return json;
    }

    return json;
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = nullptr;
      return json;
    }
    if (const auto string_literal_terminal = ctx->STRING_LITERAL()) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = parse_string_literal_ctx(string_literal_terminal);
      return json;
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
    Json json = Json::object();
    json["node"] = "HogQLXAttribute";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = visitAsString(ctx->identifier());

    if (const auto column_expr_ctx = ctx->columnExpr()) {
      json["value"] = visitAsJSON(column_expr_ctx);
    } else {
      if (const auto string_ctx = ctx->string()) {
        json["value"] = visitAsJSON(string_ctx);
      } else {
        // Default to true Constant
        json["value"] = Json::object();
        json["value"]["node"] = "Constant";
        json["value"]["value"] = true;
      }
    }

    return json;
  }

  VISIT(HogqlxChildElement) {
    if (const auto tag_element_ctx = ctx->hogqlxTagElement()) {
      return visitAsJSON(tag_element_ctx);
    }
    if (const auto text_element_ctx = ctx->hogqlxText()) {
      return visitAsJSON(text_element_ctx);
    }
    return visitAsJSON(ctx->columnExpr());
  }

  VISIT(HogqlxText) {
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = ctx->HOGQLX_TEXT_TEXT()->getText();
    return json;
  }

  VISIT(HogqlxTagElementClosed) {
    Json json = Json::object();
    json["node"] = "HogQLXTag";
    if (!is_internal) addPositionInfo(json, ctx);
    json["kind"] = visitAsString(ctx->identifier());
    json["attributes"] = visitAsVectorOfJSON(ctx->hogqlxTagAttribute());
    return json;
  }

  VISIT(HogqlxTagElementNested) {
    std::string opening = visitAsString(ctx->identifier(0));
    std::string closing = visitAsString(ctx->identifier(1));
    if (opening != closing) {
      throw SyntaxError("Opening and closing HogQLX tags must match. Got " + opening + " and " + closing);
    }

    const auto attribute_ctxs = ctx->hogqlxTagAttribute();
    vector<Json> attributes = visitAsVectorOfJSON(attribute_ctxs);

    /* ── children ───────────────────────────────────────────── */
    std::vector<Json> kept_children;
    for (const auto child_ctx : ctx->hogqlxChildElement()) {
      Json child_json = visitAsJSON(child_ctx);

      /* drop Constant nodes that are only-whitespace *and* contain a line-break */
      if (isNodeOfType(child_json, "Constant")) {
        const auto& obj = child_json.getObject();
        auto value_it = obj.find("value");
        if (value_it != obj.end() && value_it->second.isString()) {
          const string& value_text = value_it->second.getString();
          bool only_ws = true;
          for (char c : value_text) {
            if (!isspace(static_cast<unsigned char>(c))) {
              only_ws = false;
              break;
            }
          }
          bool has_newline = value_text.find('\n') != string::npos || value_text.find('\r') != string::npos;
          if (only_ws && has_newline) {
            continue;  // skip it
          }
        }
      }

      kept_children.emplace_back(std::move(child_json));  // keep it
    }

    /* if we have child nodes, validate + attach them as attribute "children" */
    if (!kept_children.empty()) {
      // Check if any attribute is named "children"
      for (const auto& attr_json : attributes) {
        if (attr_json.isObject() && attr_json.getObject().at("name").getString() == "children") {
          throw SyntaxError("Can't have a HogQLX tag with both children and a 'children' attribute");
        }
      }

      /* build children attribute */
      Json children_array = Json::array();
      for (const auto& child : kept_children) {
        children_array.pushBack(child);
      }

      Json children_attr = Json::object();
      children_attr["node"] = "HogQLXAttribute";
      children_attr["name"] = "children";
      children_attr["value"] = std::move(children_array);
      attributes.push_back(children_attr);
    }

    Json json = Json::object();
    json["node"] = "HogQLXTag";
    if (!is_internal) addPositionInfo(json, ctx);
    json["kind"] = opening;
    json["attributes"] = std::move(attributes);
    return json;
  }

  VISIT(Placeholder) {
    Json json = Json::object();
    json["node"] = "Placeholder";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->columnExpr());
    return json;
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    Json value_json = visitAsJSON(ctx->columnExpr(0));
    Json fallback_json = visitAsJSON(ctx->columnExpr(1));

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "ifNull";
    Json args = Json::array();
    args.pushBack(value_json);
    args.pushBack(fallback_json);
    json["args"] = std::move(args);
    return json;
  }

  VISIT(ColumnExprCall) {
    Json json = Json::object();
    json["node"] = "ExprCall";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = visitAsJSON(ctx->columnExpr());
    json["args"] = visitAsJSONOrEmptyArray(ctx->columnExprList());
    return json;
  }

  VISIT(ColumnExprCallSelect) {
    // 1) Parse the "function expression" from columnExpr().
    Json expr_json = visitAsJSON(ctx->columnExpr());

    // 2) Check if `expr` is a Field node with a chain of length == 1.
    //    If so, interpret that chain[0] as the function name, and the SELECT as the function argument.
    bool is_field = isNodeOfType(expr_json, "Field");

    if (is_field) {
      // Extract chain array from Field
      Json chain_json = expr_json.getObject().at("chain");

      if (!chain_json.isArray()) {
        throw ParsingError("Expected 'chain' to be an array in Field node");
      }

      if (chain_json.getArray().size() == 1) {
        // Extract function name
        string func_name = chain_json.getArray()[0].getString();

        // Build Call(name=func_name, args=[select])
        Json json = Json::object();
        json["node"] = "Call";
        if (!is_internal) addPositionInfo(json, ctx);
        json["name"] = func_name;
        Json args = Json::array();
        args.pushBack(visitAsJSON(ctx->selectSetStmt()));
        json["args"] = std::move(args);
        return json;
      }
    }

    // 3) Otherwise, build ExprCall(expr=<expr>, args=[select])
    Json json = Json::object();
    json["node"] = "ExprCall";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = expr_json;
    Json args = Json::array();
    args.pushBack(visitAsJSON(ctx->selectSetStmt()));
    json["args"] = std::move(args);
    return json;
  }

  VISIT(ColumnExprTemplateString) { return visit(ctx->templateString()); }

  VISIT(String) {
    auto string_literal = ctx->STRING_LITERAL();
    if (string_literal) {
      string text = parse_string_literal_ctx(string_literal);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = text;
      return json;
    }
    return visit(ctx->templateString());
  }

  VISIT(TemplateString) {
    auto string_contents = ctx->stringContents();

    if (string_contents.size() == 0) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = "";
      return json;
    }

    if (string_contents.size() == 1) {
      return visit(string_contents[0]);
    }

    vector<Json> args_vec = visitAsVectorOfJSON(string_contents);
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "concat";
    json["args"] = args_vec;
    return json;
  }

  VISIT(FullTemplateString) {
    auto string_contents_full = ctx->stringContentsFull();

    if (string_contents_full.size() == 0) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = "";
      return json;
    }

    if (string_contents_full.size() == 1) {
      return visit(string_contents_full[0]);
    }

    vector<Json> args_vec = visitAsVectorOfJSON(string_contents_full);
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "concat";
    Json args = Json::array();
    for (const auto& arg : args_vec) {
      args.pushBack(arg);
    }
    json["args"] = std::move(args);
    return json;
  }

  VISIT(StringContents) {
    auto string_text = ctx->STRING_TEXT();
    if (string_text) {
      string text = parse_string_text_ctx(string_text, true);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = text;
      return json;
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = "";
    return json;
  }

  VISIT(StringContentsFull) {
    auto full_string_text = ctx->FULL_STRING_TEXT();
    if (full_string_text) {
      string text = parse_string_text_ctx(full_string_text, false);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = text;
      return json;
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = "";
    return json;
  }
};
