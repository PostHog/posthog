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

  auto startToken = ctx->getStart();
  auto stopToken = ctx->getStop();

  if (startToken) {
    Json start = Json::object();
    start["line"] = static_cast<int64_t>(startToken->getLine());
    start["column"] = static_cast<int64_t>(startToken->getCharPositionInLine());
    start["offset"] = static_cast<int64_t>(startToken->getStartIndex());
    json["start"] = std::move(start);
  }

  if (stopToken) {
    Json end = Json::object();
    end["line"] = static_cast<int64_t>(stopToken->getLine());
    end["column"] = static_cast<int64_t>(stopToken->getCharPositionInLine() + stopToken->getText().length());
    end["offset"] = static_cast<int64_t>(stopToken->getStopIndex() + 1);
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
string buildJSONError(const char* errorType, const string& message, size_t start, size_t end) {
  Json json = Json::object();
  json["error"] = true;
  json["type"] = errorType;
  json["message"] = message;

  Json startPos = Json::object();
  startPos["line"] = 0;
  startPos["column"] = 0;
  startPos["offset"] = static_cast<int64_t>(start);
  json["start"] = std::move(startPos);

  Json endPos = Json::object();
  endPos["line"] = 0;
  endPos["column"] = 0;
  endPos["offset"] = static_cast<int64_t>(end);
  json["end"] = std::move(endPos);

  return json.dump();
}

// PARSING AND AST CONVERSION

class HogQLParseTreeConverter : public HogQLParserBaseVisitor {
 private:
  bool is_internal;

  const vector<string> RESERVED_KEYWORDS = {"true", "false", "null", "team_id"};

  // Check whether a serialized JSON string represents a JoinExpr at the top level.
  bool isJoinExprJson(const string& json) const {
    int depth = 0;
    bool in_string = false;

    for (size_t i = 0; i < json.size(); i++) {
      char c = json[i];

      if (c == '"' && (i == 0 || json[i - 1] != '\\')) {
        if (!in_string && depth == 1 && json.compare(i, 6, "\"node\"") == 0) {
          size_t colon_pos = json.find(":", i + 6);
          if (colon_pos == string::npos) return false;

          size_t value_start = json.find("\"", colon_pos + 1);
          if (value_start == string::npos) return false;

          size_t value_end = json.find("\"", value_start + 1);
          if (value_end == string::npos) return false;

          string node_value = json.substr(value_start + 1, value_end - value_start - 1);
          return node_value == "JoinExpr";
        }
        in_string = !in_string;
      }

      if (in_string) continue;

      if (c == '{' || c == '[') {
        depth++;
      } else if (c == '}' || c == ']') {
        if (depth > 0) depth--;
      }
    }

    return false;
  }

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
    string result = "[";
    bool first = true;
    for (auto tree : trees) {
      if (!first) {
        result += ",";
      }
      first = false;
      result += visitAsJSON(tree);
    }
    result += "]";
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
  vector<string> visitAsVectorOfJSON(vector<T> trees) {
    vector<string> ret;
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
    auto declarationCtxs = ctx->declaration();
    for (auto declarationCtx : declarationCtxs) {
      if (declarationCtx->statement() && declarationCtx->statement()->emptyStmt()) {
        continue;
      }
      declarations.pushBack(Json::raw(visitAsJSON(declarationCtx)));
    }
    json["declarations"] = std::move(declarations);
    return json.dump();
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
    json["node"] = "VariableDeclaration";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = visitAsString(ctx->identifier());
    json["expr"] = Json::raw(visitAsJSONOrNull(ctx->expression()));
    return json.dump();
  }

  VISIT(VarAssignment) {
    Json json = Json::object();
    json["node"] = "VariableAssignment";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = Json::raw(visitAsJSON(ctx->expression(0)));
    json["right"] = Json::raw(visitAsJSON(ctx->expression(1)));
    return json.dump();
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
    json["expr"] = Json::raw(visitAsJSON(ctx->expression()));
    return json.dump();
  }

  VISIT(ReturnStmt) {
    Json json = Json::object();
    json["node"] = "ReturnStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(visitAsJSONOrNull(ctx->expression()));
    return json.dump();
  }

  VISIT(ThrowStmt) {
    Json json = Json::object();
    json["node"] = "ThrowStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(visitAsJSONOrNull(ctx->expression()));
    return json.dump();
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
    arr.pushBack(Json::raw(visitAsJSON(ctx->catchStmt)));
    return arr.dump();
  }

  VISIT(TryCatchStmt) {
    Json json = Json::object();
    json["node"] = "TryCatchStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["try_stmt"] = Json::raw(visitAsJSON(ctx->tryStmt));
    Json catches = Json::array();
    auto catchBlockCtxs = ctx->catchBlock();
    for (auto catchBlockCtx : catchBlockCtxs) {
      catches.pushBack(Json::raw(visitAsJSON(catchBlockCtx)));
    }
    json["catches"] = std::move(catches);
    json["finally_stmt"] = Json::raw(visitAsJSONOrNull(ctx->finallyStmt));
    return json.dump();
  }

  VISIT(IfStmt) {
    Json json = Json::object();
    json["node"] = "IfStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(visitAsJSON(ctx->expression()));
    json["then"] = Json::raw(visitAsJSON(ctx->statement(0)));
    json["else_"] = Json::raw(visitAsJSONOrNull(ctx->statement(1)));
    return json.dump();
  }

  VISIT(WhileStmt) {
    Json json = Json::object();
    json["node"] = "WhileStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(visitAsJSON(ctx->expression()));
    json["body"] = Json::raw(visitAsJSONOrNull(ctx->statement()));
    return json.dump();
  }

  VISIT(ForStmt) {
    Json json = Json::object();
    json["node"] = "ForStatement";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->initializerVarDeclr) {
      json["initializer"] = Json::raw(visitAsJSON(ctx->initializerVarDeclr));
    } else if (ctx->initializerVarAssignment) {
      json["initializer"] = Json::raw(visitAsJSON(ctx->initializerVarAssignment));
    } else if (ctx->initializerExpression) {
      json["initializer"] = Json::raw(visitAsJSON(ctx->initializerExpression));
    } else {
      json["initializer"] = nullptr;
    }

    json["condition"] = Json::raw(visitAsJSONOrNull(ctx->condition));

    if (ctx->incrementVarDeclr) {
      json["increment"] = Json::raw(visitAsJSON(ctx->incrementVarDeclr));
    } else if (ctx->incrementVarAssignment) {
      json["increment"] = Json::raw(visitAsJSON(ctx->incrementVarAssignment));
    } else if (ctx->incrementExpression) {
      json["increment"] = Json::raw(visitAsJSON(ctx->incrementExpression));
    } else {
      json["increment"] = nullptr;
    }

    json["body"] = Json::raw(visitAsJSON(ctx->statement()));
    return json.dump();
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

    json["expr"] = Json::raw(visitAsJSON(ctx->expression()));
    json["body"] = Json::raw(visitAsJSON(ctx->statement()));
    return json.dump();
  }

  VISIT(FuncStmt) {
    Json json = Json::object();
    json["node"] = "Function";
    if (!is_internal) addPositionInfo(json, ctx);

    json["name"] = visitAsString(ctx->identifier());

    Json params = Json::array();
    auto identifierListCtx = ctx->identifierList();
    if (identifierListCtx) {
      vector<string> paramList = any_cast<vector<string>>(visit(ctx->identifierList()));
      for (const auto& param : paramList) {
        params.pushBack(param);
      }
    }
    json["params"] = std::move(params);

    json["body"] = Json::raw(visitAsJSON(ctx->block()));
    return json.dump();
  }

  VISIT(KvPairList) { return visitJSONArrayOfObjects(ctx->kvPair()); }

  VISIT(KvPair) {
    // KvPair returns an array [key, value]
    Json arr = Json::array();
    arr.pushBack(Json::raw(visitAsJSON(ctx->expression(0))));
    arr.pushBack(Json::raw(visitAsJSON(ctx->expression(1))));
    return arr.dump();
  }

  VISIT(IdentifierList) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(EmptyStmt) {
    Json json = Json::object();
    json["node"] = "ExprStatement";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = nullptr;
    return json.dump();
  }

  VISIT(Block) {
    Json json = Json::object();
    json["node"] = "Block";
    if (!is_internal) addPositionInfo(json, ctx);
    Json declarations = Json::array();
    auto declarationCtxs = ctx->declaration();
    for (auto declarationCtx : declarationCtxs) {
      if (!declarationCtx->statement() || !declarationCtx->statement()->emptyStmt()) {
        declarations.pushBack(Json::raw(visitAsJSON(declarationCtx)));
      }
    }
    json["declarations"] = std::move(declarations);
    return json.dump();
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
    auto subsequentClauses = ctx->subsequentSelectSetClause();

    if (subsequentClauses.empty()) {
      return visit(ctx->selectStmtWithParens());
    }

    Json json = Json::object();
    json["node"] = "SelectSetQuery";
    if (!is_internal) addPositionInfo(json, ctx);

    json["initial_select_query"] = Json::raw(visitAsJSON(ctx->selectStmtWithParens()));

    Json subsequentSelectQueries = Json::array();
    for (auto subsequent : subsequentClauses) {
      const char* setOperator;
      if (subsequent->UNION() && subsequent->ALL()) {
        setOperator = "UNION ALL";
      } else if (subsequent->UNION() && subsequent->DISTINCT()) {
        setOperator = "UNION DISTINCT";
      } else if (subsequent->INTERSECT() && subsequent->DISTINCT()) {
        setOperator = "INTERSECT DISTINCT";
      } else if (subsequent->INTERSECT()) {
        setOperator = "INTERSECT";
      } else if (subsequent->EXCEPT()) {
        setOperator = "EXCEPT";
      } else {
        throw SyntaxError(
            "Set operator must be one of UNION ALL, UNION DISTINCT, INTERSECT, INTERSECT DISTINCT, and EXCEPT"
        );
      }

      Json node_json = Json::object();
      node_json["node"] = "SelectSetNode";
      node_json["select_query"] = Json::raw(visitAsJSON(subsequent->selectStmtWithParens()));
      node_json["set_operator"] = setOperator;
      subsequentSelectQueries.pushBack(std::move(node_json));
    }
    json["subsequent_select_queries"] = std::move(subsequentSelectQueries);
    return json.dump();
  }

  VISIT(SelectStmt) {
    Json json = Json::object();
    json["node"] = "SelectQuery";
    if (!is_internal) addPositionInfo(json, ctx);

    // Add basic query fields
    json["ctes"] = Json::raw(visitAsJSONOrNull(ctx->withClause()));
    json["select"] = Json::raw(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    json["distinct"] = ctx->DISTINCT() ? Json(true) : Json(nullptr);
    json["select_from"] = Json::raw(visitAsJSONOrNull(ctx->fromClause()));
    json["where"] = Json::raw(visitAsJSONOrNull(ctx->whereClause()));
    json["prewhere"] = Json::raw(visitAsJSONOrNull(ctx->prewhereClause()));
    json["having"] = Json::raw(visitAsJSONOrNull(ctx->havingClause()));
    json["group_by"] = Json::raw(visitAsJSONOrNull(ctx->groupByClause()));
    json["order_by"] = Json::raw(visitAsJSONOrNull(ctx->orderByClause()));

    // Handle window clause
    auto windowClauseCtx = ctx->windowClause();
    if (windowClauseCtx) {
      auto windowExprCtxs = windowClauseCtx->windowExpr();
      auto identifierCtxs = windowClauseCtx->identifier();
      if (windowExprCtxs.size() != identifierCtxs.size()) {
        throw ParsingError("WindowClause must have a matching number of window exprs and identifiers");
      }
      Json windowExprs = Json::object();
      for (size_t i = 0; i < windowExprCtxs.size(); i++) {
        string identifier = visitAsString(identifierCtxs[i]);
        windowExprs[identifier] = Json::raw(visitAsJSON(windowExprCtxs[i]));
      }
      json["window_exprs"] = std::move(windowExprs);
    }

    // Handle offset and limit clauses
    auto limitAndOffsetClauseCtx = ctx->limitAndOffsetClause();
    auto offsetOnlyClauseCtx = ctx->offsetOnlyClause();

    if (offsetOnlyClauseCtx && !limitAndOffsetClauseCtx) {
      json["offset"] = Json::raw(visitAsJSON(offsetOnlyClauseCtx));
    }

    if (limitAndOffsetClauseCtx) {
      json["limit"] = Json::raw(visitAsJSON(limitAndOffsetClauseCtx->columnExpr(0)));

      auto offsetCtx = limitAndOffsetClauseCtx->columnExpr(1);
      if (offsetCtx) {
        json["offset"] = Json::raw(visitAsJSON(offsetCtx));
      }

      if (limitAndOffsetClauseCtx->WITH() && limitAndOffsetClauseCtx->TIES()) {
        json["limit_with_ties"] = true;
      }
    }

    // Handle limit_by clause
    auto limitByClauseCtx = ctx->limitByClause();
    if (limitByClauseCtx) {
      json["limit_by"] = Json::raw(visitAsJSON(limitByClauseCtx));
    }

    // Handle array_join clause
    auto arrayJoinClauseCtx = ctx->arrayJoinClause();
    if (arrayJoinClauseCtx) {
      string selectFromJson = visitAsJSONOrNull(ctx->fromClause());
      if (selectFromJson == "null") {
        throw SyntaxError("Using ARRAY JOIN without a FROM clause is not permitted");
      }

      if (arrayJoinClauseCtx->LEFT()) {
        json["array_join_op"] = "LEFT ARRAY JOIN";
      } else if (arrayJoinClauseCtx->INNER()) {
        json["array_join_op"] = "INNER ARRAY JOIN";
      } else {
        json["array_join_op"] = "ARRAY JOIN";
      }

      auto arrayJoinArraysCtx = arrayJoinClauseCtx->columnExprList();
      auto arrayJoinExprs = arrayJoinArraysCtx->columnExpr();

      // Validate that all array join expressions have aliases
      for (size_t i = 0; i < arrayJoinExprs.size(); i++) {
        string exprJson = visitAsJSON(arrayJoinExprs[i]);
        // Simple check: see if the JSON contains "node":"Alias"
        if (exprJson.find("\"node\":\"Alias\"") == string::npos) {
          auto relevantColumnExprCtx = arrayJoinExprs[i];
          throw SyntaxError(
              "ARRAY JOIN arrays must have an alias", relevantColumnExprCtx->getStart()->getStartIndex(),
              relevantColumnExprCtx->getStop()->getStopIndex() + 1
          );
        }
      }

      json["array_join_list"] = Json::raw(visitAsJSON(arrayJoinArraysCtx));
    }

    // Check for unsupported clauses
    if (ctx->topClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.topClause()");
    }
    if (ctx->settingsClause()) {
      throw NotImplementedError("Unsupported: SelectStmt.settingsClause()");
    }

    return json.dump();
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
    string limitExprResult = visitAsJSON(ctx->limitExpr());
    string exprs = visitAsJSON(ctx->columnExprList());

    Json json = Json::object();
    json["node"] = "LimitByExpr";
    if (!is_internal) addPositionInfo(json, ctx);

    // Check if limitExprResult is an array (contains both n and offsetValue)
    if (limitExprResult[0] == '[') {
      // It's an array, need to extract the two values
      // Parse the JSON array to get n and offsetValue by counting braces
      int braceCount = 0;
      size_t commaPos = string::npos;
      for (size_t i = 1; i < limitExprResult.length(); i++) {
        if (limitExprResult[i] == '{')
          braceCount++;
        else if (limitExprResult[i] == '}')
          braceCount--;
        else if (limitExprResult[i] == ',' && braceCount == 0) {
          commaPos = i;
          break;
        }
      }
      if (commaPos != string::npos) {
        string n = limitExprResult.substr(1, commaPos - 1);  // Skip '[' and get until ','
        string offsetValue =
            limitExprResult.substr(commaPos + 1, limitExprResult.length() - commaPos - 2);  // Get after ',' until ']'
        json["n"] = Json::raw(n);
        json["offset_value"] = Json::raw(offsetValue);
      } else {
        throw ParsingError("Invalid array format from limitExpr");
      }
    } else {
      // It's a single value, use as n with null offsetValue
      json["n"] = Json::raw(limitExprResult);
      json["offset_value"] = nullptr;
    }

    json["exprs"] = Json::raw(exprs);
    return json.dump();
  }

  VISIT(LimitExpr) {
    string first = visitAsJSON(ctx->columnExpr(0));

    // If no second expression, just return the first
    if (!ctx->columnExpr(1)) {
      return first;
    }

    // We have both limit and offset - return as a simple array
    string second = visitAsJSON(ctx->columnExpr(1));

    Json arr = Json::array();
    if (ctx->COMMA()) {
      // For "LIMIT a, b" syntax: a is offset, b is limit
      arr.pushBack(Json::raw(second));  // offset
      arr.pushBack(Json::raw(first));   // limit
    } else {
      // For "LIMIT a OFFSET b" syntax: a is limit, b is offset
      arr.pushBack(Json::raw(first));   // limit
      arr.pushBack(Json::raw(second));  // offset
    }
    return arr.dump();
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
    auto joinOpCtx = ctx->joinOp();
    string joinOp;
    if (joinOpCtx) {
      joinOp = visitAsString(joinOpCtx);
      joinOp.append(" JOIN");
    } else {
      joinOp = "JOIN";
    }

    // Get join2 and add the joinType and constraint to it
    string join2Json = visitAsJSON(ctx->joinExpr(1));
    string constraintJson = visitAsJSON(ctx->joinConstraintClause());

    // We need to inject joinType and constraint into join2Json
    // Find the position after the opening brace and node type
    size_t insertPos = join2Json.find(",", join2Json.find("\"node\""));
    if (insertPos != string::npos) {
      string injection = "\"join_type\":" + Json::escapeString(joinOp) + ",\"constraint\":" + constraintJson + ",";
      join2Json.insert(insertPos + 1, injection);
    }

    string join1Json = visitAsJSON(ctx->joinExpr(0));

    // Chain the joins together
    return chainJoinExprs(join1Json, join2Json);
  }

  VISIT(JoinExprTable) {
    string tableJson = visitAsJSON(ctx->tableExpr());
    string sampleJson = visitAsJSONOrNull(ctx->sampleClause());
    bool tableFinal = ctx->FINAL();

    // Check if table is already a JoinExpr
    bool isTableJoinExpr = isJoinExprJson(tableJson);

    if (isTableJoinExpr) {
      // Inject sample and tableFinal into the existing JoinExpr before the closing brace
      size_t insertPos = tableJson.rfind("}");
      if (insertPos != string::npos) {
        string injection = ",\"sample\":" + sampleJson + ",\"table_final\":" + (tableFinal ? "true" : "null");
        tableJson.insert(insertPos, injection);
      }
      return tableJson;
    } else {
      // Create a new JoinExpr wrapping the table
      // Note: joinType/constraint will be injected by JoinExprOp before the closing }
      Json json = Json::object();
      json["node"] = "JoinExpr";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["table"] = Json::raw(tableJson);
      json["table_final"] = tableFinal ? Json(true) : Json(nullptr);
      json["sample"] = Json::raw(sampleJson);
      json["next_join"] = nullptr;
      json["alias"] = nullptr;
      return json.dump();
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
    string columnExprListJson = visitAsJSON(ctx->columnExprList());

    // Check if we have multiple expressions (array with more than one element)
    // Simple check: count commas at depth 0
    int bracketDepth = 0;
    int exprCount = 1;
    for (char c : columnExprListJson) {
      if (c == '[' || c == '{')
        bracketDepth++;
      else if (c == ']' || c == '}')
        bracketDepth--;
      else if (c == ',' && bracketDepth == 1)
        exprCount++;
    }

    if (exprCount > 1) {
      throw NotImplementedError("Unsupported: JOIN ... ON with multiple expressions");
    }

    // Extract the single expression from the array
    size_t firstBrace = columnExprListJson.find('{');
    size_t lastBrace = columnExprListJson.rfind('}');
    string exprJson = columnExprListJson.substr(firstBrace, lastBrace - firstBrace + 1);

    Json json = Json::object();
    json["node"] = "JoinConstraint";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(exprJson);
    json["constraint_type"] = ctx->USING() ? "USING" : "ON";
    return json.dump();
  }

  VISIT(SampleClause) {
    Json json = Json::object();
    json["node"] = "SampleExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["sample_value"] = Json::raw(visitAsJSON(ctx->ratioExpr(0)));
    json["offset_value"] = Json::raw(visitAsJSONOrNull(ctx->ratioExpr(1)));
    return json.dump();
  }

  VISIT(OrderExprList) { return visitJSONArrayOfObjects(ctx->orderExpr()); }

  VISIT(OrderExpr) {
    const char* order = ctx->DESC() || ctx->DESCENDING() ? "DESC" : "ASC";
    Json json = Json::object();
    json["node"] = "OrderExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(visitAsJSON(ctx->columnExpr()));
    json["order"] = order;
    return json.dump();
  }

  VISIT(RatioExpr) {
    auto placeholderCtx = ctx->placeholder();
    if (placeholderCtx) {
      return visitAsJSON(placeholderCtx);
    }

    auto numberLiteralCtxs = ctx->numberLiteral();

    if (numberLiteralCtxs.size() > 2) {
      throw ParsingError("RatioExpr must have at most two number literals");
    } else if (numberLiteralCtxs.size() == 0) {
      throw ParsingError("RatioExpr must have at least one number literal");
    }

    auto leftCtx = numberLiteralCtxs[0];
    auto rightCtx = ctx->SLASH() && numberLiteralCtxs.size() > 1 ? numberLiteralCtxs[1] : NULL;

    Json json = Json::object();
    json["node"] = "RatioExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = Json::raw(visitAsJSON(leftCtx));
    json["right"] = Json::raw(visitAsJSONOrNull(rightCtx));
    return json.dump();
  }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  VISIT(WindowExpr) {
    auto frameCtx = ctx->winFrameClause();
    string frameJson = visitAsJSONOrNull(frameCtx);

    // Check if frame is an array (tuple of [start, end])
    bool isFrameArray = frameJson[0] == '[';
    string frameStartJson;
    string frameEndJson;

    if (isFrameArray) {
      // Extract start and end from array like [{...},{...}]
      // Find the comma between the two objects by counting braces
      int braceCount = 0;
      size_t commaPos = string::npos;
      for (size_t i = 1; i < frameJson.length(); i++) {
        if (frameJson[i] == '{')
          braceCount++;
        else if (frameJson[i] == '}')
          braceCount--;
        else if (frameJson[i] == ',' && braceCount == 0) {
          commaPos = i;
          break;
        }
      }
      if (commaPos != string::npos) {
        frameStartJson = frameJson.substr(1, commaPos - 1);                                // Skip '['
        frameEndJson = frameJson.substr(commaPos + 1, frameJson.length() - commaPos - 2);  // Skip ']'
      } else {
        throw ParsingError("WindowExpr frame must be an array of size 2");
      }
    } else {
      frameStartJson = frameJson;
      frameEndJson = "null";
    }

    string frameMethod;
    if (frameCtx && frameCtx->RANGE()) {
      frameMethod = "RANGE";
    } else if (frameCtx && frameCtx->ROWS()) {
      frameMethod = "ROWS";
    }

    Json json = Json::object();
    json["node"] = "WindowExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["partition_by"] = Json::raw(visitAsJSONOrNull(ctx->winPartitionByClause()));
    json["order_by"] = Json::raw(visitAsJSONOrNull(ctx->winOrderByClause()));
    json["frame_method"] = !frameMethod.empty() ? Json(frameMethod) : Json(nullptr);
    json["frame_start"] = Json::raw(frameStartJson);
    json["frame_end"] = Json::raw(frameEndJson);
    return json.dump();
  }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  VISIT(FrameBetween) {
    // Return an array with [start, end]
    Json arr = Json::array();
    arr.pushBack(Json::raw(visitAsJSON(ctx->winFrameBound(0))));
    arr.pushBack(Json::raw(visitAsJSON(ctx->winFrameBound(1))));
    return arr.dump();
  }

  VISIT(WinFrameBound) {
    Json json = Json::object();
    json["node"] = "WindowFrameExpr";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->PRECEDING() || ctx->FOLLOWING()) {
      json["frame_type"] = ctx->PRECEDING() ? "PRECEDING" : "FOLLOWING";
      if (ctx->numberLiteral()) {
        // Extract the value from the Constant node
        string constantJson = visitAsJSON(ctx->numberLiteral());
        // Parse out the value field from the JSON
        size_t valuePos = constantJson.find("\"value\":");
        if (valuePos != string::npos) {
          size_t valueStart = valuePos + 8;  // Skip "value":
          size_t valueEnd = constantJson.find_first_of(",}", valueStart);
          string valueStr = constantJson.substr(valueStart, valueEnd - valueStart);
          json["frame_value"] = Json::raw(valueStr);
        } else {
          json["frame_value"] = nullptr;
        }
      } else {
        json["frame_value"] = nullptr;
      }
    } else {
      json["frame_type"] = "CURRENT ROW";
    }

    return json.dump();
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
    args.pushBack(Json::raw(visitAsJSON(ctx->columnExpr(0))));
    args.pushBack(Json::raw(visitAsJSON(ctx->columnExpr(1))));
    args.pushBack(Json::raw(visitAsJSON(ctx->columnExpr(2))));
    json["args"] = std::move(args);
    return json.dump();
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
    json["expr"] = Json::raw(visitAsJSON(ctx->columnExpr()));
    json["alias"] = alias;
    return json.dump();
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
    json["right"] = Json::raw(visitAsJSON(ctx->columnExpr()));
    json["op"] = "-";
    return json.dump();
  }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectSetStmt()); }

  VISIT(ColumnExprArray) {
    Json json = Json::object();
    json["node"] = "Array";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = Json::raw(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    return json.dump();
  }

  VISIT(ColumnExprDict) {
    Json json = Json::object();
    json["node"] = "Dict";
    if (!is_internal) addPositionInfo(json, ctx);
    json["items"] = Json::raw(visitAsJSONOrEmptyArray(ctx->kvPairList()));
    return json.dump();
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
    json["left"] = Json::raw(visitAsJSON(ctx->columnExpr(0)));
    json["right"] = Json::raw(visitAsJSON(ctx->right));
    json["op"] = op;
    return json.dump();
  }

  VISIT(ColumnExprPrecedence2) {
    string leftJson = visitAsJSON(ctx->left);
    string rightJson = visitAsJSON(ctx->right);

    if (ctx->PLUS()) {
      Json json = Json::object();
      json["node"] = "ArithmeticOperation";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["left"] = Json::raw(leftJson);
      json["right"] = Json::raw(rightJson);
      json["op"] = "+";
      return json.dump();
    } else if (ctx->DASH()) {
      Json json = Json::object();
      json["node"] = "ArithmeticOperation";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["left"] = Json::raw(leftJson);
      json["right"] = Json::raw(rightJson);
      json["op"] = "-";
      return json.dump();
    } else if (ctx->CONCAT()) {
      // Check if left or right are already concat calls
      bool isLeftConcat =
          leftJson.find("\"node\":\"Call\"") != string::npos && leftJson.find("\"name\":\"concat\"") != string::npos;
      bool isRightConcat =
          rightJson.find("\"node\":\"Call\"") != string::npos && rightJson.find("\"name\":\"concat\"") != string::npos;

      // Build args string manually for concat flattening
      string argsContent;

      // Extract args from left if it's a concat, otherwise use left itself
      if (isLeftConcat) {
        size_t argsPos = leftJson.find("\"args\":[");
        if (argsPos != string::npos) {
          size_t argsStart = leftJson.find('[', argsPos);
          int depth = 0;
          size_t i = argsStart;
          for (; i < leftJson.length(); i++) {
            if (leftJson[i] == '[' || leftJson[i] == '{')
              depth++;
            else if (leftJson[i] == ']' || leftJson[i] == '}') {
              depth--;
              if (depth == 0 && leftJson[i] == ']') break;
            }
          }
          argsContent = leftJson.substr(argsStart + 1, i - argsStart - 1);
        }
      } else {
        argsContent = leftJson;
      }

      // Extract args from right if it's a concat, otherwise use right itself
      if (isRightConcat) {
        size_t argsPos = rightJson.find("\"args\":[");
        if (argsPos != string::npos) {
          size_t argsStart = rightJson.find('[', argsPos);
          int depth = 0;
          size_t i = argsStart;
          for (; i < rightJson.length(); i++) {
            if (rightJson[i] == '[' || rightJson[i] == '{')
              depth++;
            else if (rightJson[i] == ']' || rightJson[i] == '}') {
              depth--;
              if (depth == 0 && rightJson[i] == ']') break;
            }
          }
          string rightArgsContent = rightJson.substr(argsStart + 1, i - argsStart - 1);
          argsContent += "," + rightArgsContent;
        }
      } else {
        argsContent += "," + rightJson;
      }

      Json json = Json::object();
      json["node"] = "Call";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["name"] = "concat";
      json["args"] = Json::raw("[" + argsContent + "]");
      return json.dump();
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
    json["left"] = Json::raw(visitAsJSON(ctx->left));
    json["right"] = Json::raw(visitAsJSON(ctx->right));
    json["op"] = op;
    return json.dump();
  }

  VISIT(ColumnExprInterval) {
    auto intervalCtx = ctx->interval();
    const char* name;
    if (intervalCtx->SECOND()) {
      name = "toIntervalSecond";
    } else if (intervalCtx->MINUTE()) {
      name = "toIntervalMinute";
    } else if (intervalCtx->HOUR()) {
      name = "toIntervalHour";
    } else if (intervalCtx->DAY()) {
      name = "toIntervalDay";
    } else if (intervalCtx->WEEK()) {
      name = "toIntervalWeek";
    } else if (intervalCtx->MONTH()) {
      name = "toIntervalMonth";
    } else if (intervalCtx->QUARTER()) {
      name = "toIntervalQuarter";
    } else if (intervalCtx->YEAR()) {
      name = "toIntervalYear";
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprInterval");
    }

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    Json args = Json::array();
    args.pushBack(Json::raw(visitAsJSON(ctx->columnExpr())));
    json["args"] = std::move(args);
    return json.dump();
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
    return json.dump();
  }

  VISIT(ColumnExprIsNull) {
    Json json = Json::object();
    json["node"] = "CompareOperation";
    if (!is_internal) addPositionInfo(json, ctx);
    json["left"] = Json::raw(visitAsJSON(ctx->columnExpr()));
    // Create null constant for right side
    Json nullConstant = Json::object();
    nullConstant["node"] = "Constant";
    nullConstant["value"] = nullptr;
    json["right"] = std::move(nullConstant);
    json["op"] = ctx->NOT() ? "!=" : "==";
    return json.dump();
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
    args.pushBack(Json::raw(visitAsJSON(ctx->columnExpr())));
    args.pushBack(Json::raw(visitAsJSON(ctx->string())));
    json["args"] = std::move(args);
    return json.dump();
  }

  VISIT(ColumnExprTuple) {
    Json json = Json::object();
    json["node"] = "Tuple";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = Json::raw(visitAsJSONOrEmptyArray(ctx->columnExprList()));
    return json.dump();
  }

  VISIT(ColumnExprArrayAccess) {
    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = Json::raw(visitAsJSON(ctx->columnExpr(0)));
    json["property"] = Json::raw(visitAsJSON(ctx->columnExpr(1)));
    return json.dump();
  }

  VISIT(ColumnExprNullArrayAccess) {
    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = Json::raw(visitAsJSON(ctx->columnExpr(0)));
    json["property"] = Json::raw(visitAsJSON(ctx->columnExpr(1)));
    json["nullish"] = true;
    return json.dump();
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
    json["array"] = Json::raw(visitAsJSON(ctx->columnExpr()));
    json["property"] = std::move(property);
    return json.dump();
  }

  VISIT(ColumnExprNullPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());

    // Build property Constant node
    Json property_json = Json::object();
    property_json["node"] = "Constant";
    property_json["value"] = identifier;

    string object_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "ArrayAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["array"] = Json::raw(object_json);
    json["property"] = std::move(property_json);
    json["nullish"] = true;
    return json.dump();
  }

  VISIT(ColumnExprBetween) {
    string expr_json = visitAsJSON(ctx->columnExpr(0));
    string low_json = visitAsJSON(ctx->columnExpr(1));
    string high_json = visitAsJSON(ctx->columnExpr(2));

    Json json = Json::object();
    json["node"] = "BetweenExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(expr_json);
    json["low"] = Json::raw(low_json);
    json["high"] = Json::raw(high_json);
    json["negated"] = ctx->NOT() != nullptr;
    return json.dump();
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

    Json json = Json::object();
    json["node"] = "And";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = Json::raw("[" + boost::algorithm::join(exprs, ",") + "]");
    return json.dump();
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

    Json json = Json::object();
    json["node"] = "Or";
    if (!is_internal) addPositionInfo(json, ctx);
    json["exprs"] = Json::raw("[" + boost::algorithm::join(exprs, ",") + "]");
    return json.dump();
  }

  VISIT(ColumnExprTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    string tuple_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "TupleAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["tuple"] = Json::raw(tuple_json);
    json["index"] = index_value;
    return json.dump();
  }

  VISIT(ColumnExprNullTupleAccess) {
    string index_str = ctx->DECIMAL_LITERAL()->getText();
    int64_t index_value = stoll(index_str);
    string tuple_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "TupleAccess";
    if (!is_internal) addPositionInfo(json, ctx);
    json["tuple"] = Json::raw(tuple_json);
    json["index"] = index_value;
    json["nullish"] = true;
    return json.dump();
  }

  VISIT(ColumnExprCase) {
    auto column_expr_ctx = ctx->columnExpr();
    size_t columns_size = column_expr_ctx.size();
    vector<string> columns = visitAsVectorOfJSON(column_expr_ctx);

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);

    if (ctx->caseExpr) {
      // CASE expr WHEN ... THEN ... ELSE ... END
      // Transform to: transform(expr, [conditions], [results], else_result)
      json["name"] = "transform";

      Json args = Json::array();

      // arg_0: the case expression
      args.pushBack(Json::raw(columns[0]));

      // arg_1: Array of conditions (odd indices from 1 to columns_size-2)
      Json conditions_array = Json::object();
      conditions_array["node"] = "Array";
      conditions_array["exprs"] = Json::raw("[" + [&]() {
        vector<string> conds;
        for (size_t index = 1; index < columns_size - 1; index++) {
          if ((index - 1) % 2 == 0) {
            conds.push_back(columns[index]);
          }
        }
        return boost::algorithm::join(conds, ",");
      }() + "]");
      args.pushBack(std::move(conditions_array));

      // arg_2: Array of results (even indices from 1 to columns_size-2)
      Json results_array = Json::object();
      results_array["node"] = "Array";
      results_array["exprs"] = Json::raw("[" + [&]() {
        vector<string> ress;
        for (size_t index = 1; index < columns_size - 1; index++) {
          if ((index - 1) % 2 == 1) {
            ress.push_back(columns[index]);
          }
        }
        return boost::algorithm::join(ress, ",");
      }() + "]");
      args.pushBack(std::move(results_array));

      // arg_3: else result (last element)
      args.pushBack(Json::Raw(columns[columns_size - 1]));

      json["args"] = args;
    } else {
      // CASE WHEN ... THEN ... ELSE ... END
      json["name"] = columns_size == 3 ? "if" : "multiIf";
      json["args"] = Json::raw("[" + boost::algorithm::join(columns, ",") + "]");
    }

    return json.dump();
  }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) {
    string expr_json = visitAsJSON(ctx->columnExpr());
    Json json = Json::object();
    json["node"] = "Not";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(expr_json);
    return json.dump();
  }

  VISIT(ColumnExprWinFunctionTarget) {
    auto column_expr_list_ctx = ctx->columnExprs;
    string name = visitAsString(ctx->identifier(0));
    string over_identifier = visitAsString(ctx->identifier(1));
    string exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    string args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);

    Json json = Json::object();
    json["node"] = "WindowFunction";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["exprs"] = Json::raw(exprs_json);
    json["args"] = Json::raw(args_json);
    json["over_identifier"] = over_identifier;
    return json.dump();
  }

  VISIT(ColumnExprWinFunction) {
    string identifier = visitAsString(ctx->identifier());
    auto column_expr_list_ctx = ctx->columnExprs;
    string exprs_json = visitAsJSONOrEmptyArray(column_expr_list_ctx);
    string args_json = visitAsJSONOrEmptyArray(ctx->columnArgList);
    string over_expr_json = visitAsJSONOrNull(ctx->windowExpr());

    Json json = Json::object();
    json["node"] = "WindowFunction";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = identifier;
    json["exprs"] = Json::raw(exprs_json);
    json["args"] = Json::raw(args_json);
    json["over_expr"] = Json::raw(over_expr_json);
    return json.dump();
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

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["params"] = Json::raw(params_json);
    json["args"] = Json::raw(args_json);
    json["distinct"] = ctx->DISTINCT() != nullptr;
    return json.dump();
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
    return json.dump();
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

    vector<string> args_vec = visitAsVectorOfStrings(ctx->identifier());

    Json json = Json::object();
    json["node"] = "Lambda";
    if (!is_internal) addPositionInfo(json, ctx);
    Json args = Json::array();
    for (const auto& arg : args_vec) {
      args.pushBack(arg);
    }
    json["args"] = std::move(args);
    json["expr"] = Json::raw(expr_json);
    return json.dump();
  }

  VISIT(WithExprList) {
    // Build a JSON object (dictionary) mapping CTE names to CTE objects
    Json json = Json::object();

    for (auto with_expr_ctx : ctx->withExpr()) {
      string cte_json = visitAsJSON(with_expr_ctx);

      // Extract the "name" field from the CTE JSON to use as the key
      size_t name_pos = cte_json.find("\"name\":\"");
      if (name_pos != string::npos) {
        size_t name_start = name_pos + 8;  // after "name":"
        size_t name_end = cte_json.find("\"", name_start);
        string name = cte_json.substr(name_start, name_end - name_start);

        json[name] = Json::raw(cte_json);
      }
    }

    return json.dump();
  }

  VISIT(WithExprSubquery) {
    string name = visitAsString(ctx->identifier());
    string expr_json = visitAsJSON(ctx->selectSetStmt());

    Json json = Json::object();
    json["node"] = "CTE";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["expr"] = Json::raw(expr_json);
    json["cte_type"] = "subquery";
    return json.dump();
  }

  VISIT(WithExprColumn) {
    string name = visitAsString(ctx->identifier());
    string expr_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "CTE";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["expr"] = Json::raw(expr_json);
    json["cte_type"] = "column";
    return json.dump();
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
        Json json = Json::object();
        json["node"] = "Constant";
        if (!is_internal) addPositionInfo(json, ctx);
        json["value"] = true;
        return json.dump();
      }
      if (!text.compare("false")) {
        Json json = Json::object();
        json["node"] = "Constant";
        if (!is_internal) addPositionInfo(json, ctx);
        json["value"] = false;
        return json.dump();
      }
      Json json = Json::object();
      json["node"] = "Field";
      if (!is_internal) addPositionInfo(json, ctx);
      Json chain = Json::array();
      for (const auto& part : nested) {
        chain.pushBack(part);
      }
      json["chain"] = std::move(chain);
      return json.dump();
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
    return json.dump();
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
    return json.dump();
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

    // Check if table is already a JoinExpr
    bool is_table_a_join_expr = isJoinExprJson(table_json);
    if (is_table_a_join_expr) {
      // Inject alias into existing JoinExpr before the closing brace
      size_t insert_pos = table_json.rfind("}");
      if (insert_pos != string::npos) {
        string alias_injection = ",\"alias\":" + Json::escapeString(alias);
        table_json.insert(insert_pos, alias_injection);
      }
      return table_json;
    }

    // Wrap table in a JoinExpr with alias
    // Note: sample/table_final/join_type/constraint will be injected by JoinExprTable/JoinExprOp before the final }
    Json json = Json::object();
    json["node"] = "JoinExpr";
    if (!is_internal) addPositionInfo(json, ctx);
    json["table"] = Json::raw(table_json);
    json["alias"] = alias;
    json["next_join"] = nullptr;
    return json.dump();
  }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  VISIT(TableExprTag) { return visit(ctx->hogqlxTagElement()); }

  VISIT(TableFunctionExpr) {
    string table_name = visitAsString(ctx->identifier());
    auto table_args_ctx = ctx->tableArgList();
    string table_args_json = table_args_ctx ? visitAsJSON(table_args_ctx) : "[]";

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
    json["table_args"] = Json::raw(table_args_json);
    return json.dump();
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

    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);

    if (text.find(".") != string::npos || text.find("e") != string::npos || !text.compare("-inf") ||
        !text.compare("inf") || !text.compare("nan")) {
      json["value"] = stod(text);  // Float
    } else {
      json["value"] = stoll(text);  // Integer
    }

    return json.dump();
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["value"] = nullptr;
      return json.dump();
    }
    auto string_literal_terminal = ctx->STRING_LITERAL();
    if (string_literal_terminal) {
      string text = parse_string_literal_ctx(string_literal_terminal);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["value"] = text;
      return json.dump();
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
        Json value_obj = Json::object();
        value_obj["node"] = "Constant";
        value_obj["value"] = true;
        value_json = value_obj.dump();
      }
    }

    Json json = Json::object();
    json["node"] = "HogQLXAttribute";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = name;
    json["value"] = Json::raw(value_json);
    return json.dump();
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

    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = text;
    return json.dump();
  }

  VISIT(HogqlxTagElementClosed) {
    string kind = visitAsString(ctx->identifier());
    vector<string> attributes_vec = visitAsVectorOfJSON(ctx->hogqlxTagAttribute());

    Json json = Json::object();
    json["node"] = "HogQLXTag";
    if (!is_internal) addPositionInfo(json, ctx);
    json["kind"] = kind;
    Json attributes = Json::array();
    for (const auto& attr : attributes_vec) {
      attributes.pushBack(Json::raw(attr));
    }
    json["attributes"] = std::move(attributes);
    return json.dump();
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
      Json children_array = Json::array();
      for (const auto& child : kept_children) {
        children_array.pushBack(Json::raw(child));
      }

      Json children_attr = Json::object();
      children_attr["node"] = "HogQLXAttribute";
      children_attr["name"] = "children";
      children_attr["value"] = std::move(children_array);

      attributes.push_back(children_attr.dump());
    }

    Json json = Json::object();
    json["node"] = "HogQLXTag";
    if (!is_internal) addPositionInfo(json, ctx);
    json["kind"] = opening;
    Json attrs = Json::array();
    for (const auto& attr : attributes) {
      attrs.pushBack(Json::raw(attr));
    }
    json["attributes"] = std::move(attrs);
    return json.dump();
  }

  VISIT(Placeholder) {
    string expr_json = visitAsJSON(ctx->columnExpr());

    Json json = Json::object();
    json["node"] = "Placeholder";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(expr_json);
    return json.dump();
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    string value_json = visitAsJSON(ctx->columnExpr(0));
    string fallback_json = visitAsJSON(ctx->columnExpr(1));

    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "ifNull";
    Json args = Json::array();
    args.pushBack(Json::raw(value_json));
    args.pushBack(Json::raw(fallback_json));
    json["args"] = std::move(args);
    return json.dump();
  }

  VISIT(ColumnExprCall) {
    string expr_json = visitAsJSON(ctx->columnExpr());
    string args_json = visitAsJSONOrEmptyArray(ctx->columnExprList());

    Json json = Json::object();
    json["node"] = "ExprCall";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(expr_json);
    json["args"] = Json::raw(args_json);
    return json.dump();
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

          Json json = Json::object();
          json["node"] = "Call";
          if (!is_internal) {
            addPositionInfo(json, ctx);
          }
          json["name"] = func_name;
          Json args = Json::array();
          args.pushBack(Json::raw(select_json));
          json["args"] = std::move(args);
          return json.dump();
        }
      }
    }

    // 3) Otherwise, build ExprCall(expr=<expr>, args=[select])
    string select_json = visitAsJSON(ctx->selectSetStmt());

    Json json = Json::object();
    json["node"] = "ExprCall";
    if (!is_internal) addPositionInfo(json, ctx);
    json["expr"] = Json::raw(expr_json);
    Json args = Json::array();
    args.pushBack(Json::raw(select_json));
    json["args"] = std::move(args);
    return json.dump();
  }

  VISIT(ColumnExprTemplateString) { return visit(ctx->templateString()); }

  VISIT(String) {
    auto string_literal = ctx->STRING_LITERAL();
    if (string_literal) {
      string text = parse_string_literal_ctx(string_literal);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) {
        addPositionInfo(json, ctx);
      }
      json["value"] = text;
      return json.dump();
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
      return json.dump();
    }

    if (string_contents.size() == 1) {
      return visit(string_contents[0]);
    }

    vector<string> args_vec = visitAsVectorOfJSON(string_contents);
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "concat";
    Json args = Json::array();
    for (const auto& arg : args_vec) {
      args.pushBack(Json::raw(arg));
    }
    json["args"] = std::move(args);
    return json.dump();
  }

  VISIT(FullTemplateString) {
    auto string_contents_full = ctx->stringContentsFull();

    if (string_contents_full.size() == 0) {
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = "";
      return json.dump();
    }

    if (string_contents_full.size() == 1) {
      return visit(string_contents_full[0]);
    }

    vector<string> args_vec = visitAsVectorOfJSON(string_contents_full);
    Json json = Json::object();
    json["node"] = "Call";
    if (!is_internal) addPositionInfo(json, ctx);
    json["name"] = "concat";
    Json args = Json::array();
    for (const auto& arg : args_vec) {
      args.pushBack(Json::raw(arg));
    }
    json["args"] = std::move(args);
    return json.dump();
  }

  VISIT(StringContents) {
    auto string_text = ctx->STRING_TEXT();
    if (string_text) {
      string text = parse_string_text_ctx(string_text, true);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = text;
      return json.dump();
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = "";
    return json.dump();
  }

  VISIT(StringContentsFull) {
    auto full_string_text = ctx->FULL_STRING_TEXT();
    if (full_string_text) {
      string text = parse_string_text_ctx(full_string_text, false);
      Json json = Json::object();
      json["node"] = "Constant";
      if (!is_internal) addPositionInfo(json, ctx);
      json["value"] = text;
      return json.dump();
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    Json json = Json::object();
    json["node"] = "Constant";
    if (!is_internal) addPositionInfo(json, ctx);
    json["value"] = "";
    return json.dump();
  }
};
