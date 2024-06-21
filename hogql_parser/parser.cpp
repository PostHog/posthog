#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <boost/algorithm/string.hpp>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "parser.h"
#include "string.h"

#define VISIT(RULE) any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                                \
  VISIT(RULE) {                                                \
    throw NotImplementedError("Unsupported rule: " #RULE); \
  }

#define HANDLE_HOGQL_ERROR(TYPE, OTHER_CLEANUP)                                                     \
  (const TYPE& e) {                                                                                     \
    string err_what = e.what();                                                                         \
    PyObject *error_type = NULL, *py_err_args = NULL, *py_err = NULL, *py_start = NULL, *py_end = NULL; \
    int err_indicator = 0;                                                                              \
    error_type = PyObject_GetAttrString(state->errors_module, #TYPE);                                   \
    if (!error_type) goto exit##TYPE;                                                                   \
    py_err_args = Py_BuildValue("(s#)", err_what.data(), err_what.size());                              \
    if (!py_err_args) goto exit##TYPE;                                                                  \
    py_err = PyObject_CallObject(error_type, py_err_args);                                              \
    if (!py_err) goto exit##TYPE;                                                                       \
    py_start = PyLong_FromSize_t(e.start);                                                              \
    if (!py_start) goto exit##TYPE;                                                                     \
    py_end = PyLong_FromSize_t(e.end);                                                                  \
    if (!py_end) goto exit##TYPE;                                                                       \
    err_indicator = PyObject_SetAttrString(py_err, "start", py_start);                                  \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    err_indicator = PyObject_SetAttrString(py_err, "end", py_end);                                      \
    if (err_indicator == -1) goto exit##TYPE;                                                           \
    PyErr_SetObject(error_type, py_err);                                                                \
    exit##TYPE :;                                                                                       \
    Py_XDECREF(py_end);                                                                                 \
    Py_XDECREF(py_start);                                                                               \
    Py_XDECREF(py_err);                                                                                 \
    Py_XDECREF(error_type);                                                                             \
    OTHER_CLEANUP                                                                                       \
    return NULL;                                                                                        \
  }

#define RETURN_NEW_AST_NODE(TYPE_NAME, KWARGS_FORMAT, ...)                                                    \
  PyObject* ret = build_ast_node(TYPE_NAME, KWARGS_FORMAT, __VA_ARGS__);                                      \
  /* Fortunately we don't need to care about decrementing Py_BuildValue/Py_VaBuildValue args, */              \
  /* so just throw is enough: https://github.com/python/cpython/blob/a254120f/Python/modsupport.c#L147-L148*/ \
  if (!ret) throw PyInternalError();                                                                      \
  return ret

using namespace std;

// PYTHON UTILS (`X_` stands for "extension")

// Extend `list` with `extension` in-place. Return 0 on success, -1 on error.
int X_PyList_Extend(PyObject* list, PyObject* extension) {
  Py_ssize_t list_size = PyList_Size(list);
  if (list_size == -1) {
    return -1;
  }
  Py_ssize_t extension_size = PyList_Size(extension);
  if (extension_size == -1) {
    return -1;
  }
  return PyList_SetSlice(list, list_size, list_size + extension_size, extension);
}

// Decref all elements of a vector.
void X_Py_DECREF_ALL(vector<PyObject*> objects) {
  for (PyObject* object : objects) {
    Py_DECREF(object);
  }
}

// Construct a Python list from a vector of strings. Return value: New reference (or NULL on error).
PyObject* X_PyList_FromStrings(const vector<string>& items) {
  PyObject* list = PyList_New(items.size());
  if (!list) {
    return NULL;
  }
  for (size_t i = 0; i < items.size(); i++) {
    PyObject* value = PyUnicode_FromStringAndSize(items[i].data(), items[i].size());
    if (!value) {
      Py_DECREF(list);
      return NULL;
    }
    PyList_SET_ITEM(list, i, value);
  }
  return list;
}

// PARSING AND AST CONVERSION

class HogQLParseTreeConverter : public HogQLParserBaseVisitor {
 private:
  parser_state* state;
  bool is_internal;

  const vector<string> RESERVED_KEYWORDS = {"true", "false", "null", "team_id"};

  // Build an AST node of the specified type. Return value: New reference.
  PyObject* build_ast_node(const char* type_name, const char* kwargs_format, ...) {
    va_list valist;
    va_start(valist, kwargs_format);
    PyObject *node_type = NULL, *args = NULL, *kwargs = NULL, *ast_node = NULL;
    node_type = PyObject_GetAttrString(state->ast_module, type_name);
    if (!node_type) goto exit;
    args = PyTuple_New(0);
    if (!args) goto exit;
    kwargs = Py_VaBuildValue(kwargs_format, valist);
    if (!kwargs) goto exit;
    ast_node = PyObject_Call(node_type, args, kwargs);
  exit:
    va_end(valist);
    Py_XDECREF(kwargs);
    Py_XDECREF(args);
    Py_XDECREF(node_type);
    return ast_node;
  }

  // Return the specified member of the specified enum. Return value: New reference.
  PyObject* get_ast_enum_member(const char* enum_name, const char* enum_member_name) {
    PyObject* enum_type = PyObject_GetAttrString(state->ast_module, enum_name);
    if (!enum_type) {
      return NULL;
    }
    PyObject* enum_member = PyObject_GetAttrString(enum_type, enum_member_name);
    Py_DECREF(enum_type);
    if (!enum_member) {
      return NULL;
    }
    return enum_member;
  }

#define IS_AST_NODE_INSTANCE_IMPL(HOGQL_MODULE, TYPE_NAME)                               \
  PyObject* node_type = PyObject_GetAttrString(state->HOGQL_MODULE##_module, TYPE_NAME); \
  if (!node_type) return -1;                                                             \
  int ret = PyObject_IsInstance(obj, node_type);                                         \
  Py_DECREF(node_type);                                                                  \
  return ret;

  // Return 1 if the passed object is an instance of the specified AST node type, 0 if not, -1 if an error occurred.
  int is_ast_node_instance(PyObject* obj, const char* type_name) { IS_AST_NODE_INSTANCE_IMPL(ast, type_name) }

  // Return 1 if the passed object is an instance of _any_ AST node type, 0 if not, -1 if an error occurred.
  int is_ast_node_instance(PyObject* obj) { IS_AST_NODE_INSTANCE_IMPL(base, "AST") }

#undef IS_AST_NODE_INSTANCE_IMPL

 public:
  HogQLParseTreeConverter(parser_state* state, bool is_internal) : state(state), is_internal(is_internal) {}

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
    // Visit the parse tree node (while making sure that nodes/errors have spans - except for internal expressions)
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
    if (!is_internal && node.has_value() && node.type() == typeid(PyObject*)) {
      PyObject* py_node = any_cast<PyObject*>(node);
      if (py_node) {
        int is_ast = is_ast_node_instance(py_node);
        if (is_ast == -1) {
          Py_DECREF(py_node);
          throw PyInternalError();
        }
        if (is_ast) {
          PyObject *py_start = NULL, *py_end = NULL;
          int err_indicator = 0;
          py_start = PyLong_FromSize_t(start);
          if (!py_start) goto error;
          py_end = PyLong_FromSize_t(stop + 1);
          if (!py_end) goto error;
          err_indicator = PyObject_SetAttrString(py_node, "start", py_start);
          if (err_indicator == -1) goto error;
          err_indicator = PyObject_SetAttrString(py_node, "end", py_end);
          if (err_indicator == -1) goto error;
          goto success;
        error:
          Py_XDECREF(py_start);
          Py_XDECREF(py_end);
          Py_DECREF(py_node);
          throw PyInternalError();
        success:
          Py_XDECREF(py_start);
          Py_XDECREF(py_end);
        }
      }
    }
    return node;
  }

  // This is the only method that should actually be called from outside the class.
  // Convert the parse tree to an AST node result. If an error has occurred in conversion, handle it gracefully.
  PyObject* visitAsPyObjectFinal(antlr4::tree::ParseTree* tree) {
    try {
      return visitAsPyObject(tree);
    } catch HANDLE_HOGQL_ERROR(SyntaxError, ) catch HANDLE_HOGQL_ERROR(
        NotImplementedError,
    ) catch HANDLE_HOGQL_ERROR(ParsingError, ) catch (const PyInternalError& e) {
      return NULL;
    } catch (const bad_any_cast& e) {
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "ParsingError");
      if (error_type) {
        PyErr_SetString(error_type, "Parsing failed due to bad type casting");
      }
      return NULL;
    }
  }

  PyObject* visitAsPyObject(antlr4::tree::ParseTree* tree) {
    PyObject* ret = any_cast<PyObject*>(visit(tree));
    if (!ret) {
      throw ParsingError(
          "Rule resulted in a null PyObject pointer. A PyInternalError should have been raised instead."
      );
    }
    return ret;
  }

  PyObject* visitAsPyObjectOrNone(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      Py_RETURN_NONE;
    }
    return visitAsPyObject(tree);
  }

  PyObject* visitAsPyObjectOrEmptyList(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      PyObject* list = PyList_New(0);
      if (!list) throw PyInternalError();
      return list;
    }
    return visitAsPyObject(tree);
  }

  // T has to be used in place of antlr4::tree::ParseTree* here, because there's no conversion from the child class
  // to its parent within vectors
  template <typename T>
  PyObject* visitPyListOfObjects(vector<T> tree) {
    PyObject* ret = PyList_New(tree.size());
    if (!ret) {
      throw PyInternalError();
    }
    for (size_t i = 0; i < tree.size(); i++) {
      try {
        PyList_SET_ITEM(ret, i, visitAsPyObject(tree[i]));
      } catch (...) {
        Py_DECREF(ret);
        throw;
      }
    }
    return ret;
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

  VISIT(Program) {
    PyObject* declarations = PyList_New(0);
    if (!declarations) {
      throw PyInternalError();
    }
    auto declaration_ctxs = ctx->declaration();
    for (auto declaration_ctx : declaration_ctxs) {
      if (declaration_ctx->statement() && declaration_ctx->statement()->emptyStmt()) {
        continue;
      }
      PyObject* statement = Py_None;
      try {
        statement = visitAsPyObject(declaration_ctx);
        int append_code = PyList_Append(declarations, statement);
        Py_DECREF(statement);
        if (append_code == -1) {
          throw PyInternalError();
        }
      } catch (...) {
        Py_DECREF(declarations);
        throw;
      }
    }
    PyObject* ret = build_ast_node("Program", "{s:N}", "declarations", declarations);
    if (!ret) {
      Py_DECREF(declarations);
      throw PyInternalError();
    }
    return ret;
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

  VISIT(Expression) {
    return visit(ctx->columnExpr());
  }

  VISIT(VarDecl) {
    string name = visitAsString(ctx->identifier());
    PyObject* expr = visitAsPyObjectOrNone(ctx->expression());
    PyObject* ret = build_ast_node("VariableDeclaration", "{s:s#,s:N}", "name", name.data(), name.size(), "expr", expr);
    if (!ret) {
      Py_DECREF(expr);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(VarAssignment) {
    PyObject* left = visitAsPyObject(ctx->expression(0));
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->expression(1));
    } catch (...) {
      Py_DECREF(left);
      throw;
    }
    PyObject* ret = build_ast_node("VariableAssignment", "{s:N,s:N}", "left", left, "right", right);
    if (!ret) {
      Py_DECREF(left);
      Py_DECREF(right);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(Statement) {
    auto return_stmt_ctx = ctx->returnStmt();
    if (return_stmt_ctx) {
      return visit(return_stmt_ctx);
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

    throw ParsingError("Statement must be one of returnStmt, ifStmt, whileStmt, forStmt, funcStmt, varAssignment, "
                       "block, exprStmt, or emptyStmt");
  }

  VISIT(ExprStmt) {
    PyObject* expr;
    try {
      expr = visitAsPyObject(ctx->expression());
    } catch (...) {
      throw;
    }
    PyObject* ret = build_ast_node("ExprStatement", "{s:N}", "expr", expr);
    if (!ret) {
      Py_DECREF(expr);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(ReturnStmt) {
    PyObject* expr;
    try {
      expr = visitAsPyObjectOrNone(ctx->expression());
    } catch (...) {
      throw;
    }
    PyObject* ret = build_ast_node("ReturnStatement", "{s:N}", "expr", expr);
    if (!ret) {
      Py_DECREF(expr);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(IfStmt) {
    PyObject* expr;
    try {
      expr = visitAsPyObject(ctx->expression());
    } catch (...) {
      throw;
    }
    PyObject* then_stmt;
    try {
      then_stmt = visitAsPyObject(ctx->statement(0));
    } catch (...) {
      Py_DECREF(expr);
      throw;
    }
    PyObject* else_stmt;
    try {
      else_stmt = visitAsPyObjectOrNone(ctx->statement(1));
    } catch (...) {
      Py_DECREF(expr);
      Py_DECREF(then_stmt);
      throw;
    }
    PyObject* ret = build_ast_node("IfStatement", "{s:N,s:N,s:N}", "expr", expr, "then", then_stmt, "else_", else_stmt);
    if (!ret) {
      Py_DECREF(expr);
      Py_DECREF(then_stmt);
      Py_DECREF(else_stmt);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(WhileStmt) {
    PyObject* expr;
    try {
      expr = visitAsPyObject(ctx->expression());
    } catch (...) {
      throw;
    }
    PyObject* body;
    try {
      body = visitAsPyObjectOrNone(ctx->statement());
    } catch (...) {
      Py_DECREF(expr);
      throw;
    }
    PyObject* ret = build_ast_node("WhileStatement", "{s:N,s:N}", "expr", expr, "body", body);
    if (!ret) {
      Py_DECREF(expr);
      Py_DECREF(body);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(ForStmt) {
    PyObject* initializer;
    if (ctx->initializerVarDeclr) {
      initializer = visitAsPyObject(ctx->initializerVarDeclr);
    } else if (ctx->initializerVarAssignment) {
      initializer = visitAsPyObject(ctx->initializerVarAssignment);
    } else if (ctx->initializerExpression) {
      initializer = visitAsPyObject(ctx->initializerExpression);
    } else {
      initializer = Py_None;
      Py_INCREF(initializer);
    }

    PyObject* condition;
    try {
      condition = visitAsPyObjectOrNone(ctx->condition);
    } catch (...) {
      Py_DECREF(initializer);
      throw;
    }

    PyObject* increment;
    auto increment_var_declr_ctx = ctx->incrementVarDeclr;
    auto increment_var_assignment_ctx = ctx->incrementVarAssignment;
    auto increment_expression_ctx = ctx->incrementExpression;
    if (increment_var_declr_ctx) {
      try {
        increment = visitAsPyObject(increment_var_declr_ctx);
      } catch (...) {
        Py_DECREF(initializer);
        Py_DECREF(condition);
        throw;
      }
    } else if (increment_var_assignment_ctx) {
      try {
        increment = visitAsPyObject(increment_var_assignment_ctx);
      } catch (...) {
        Py_DECREF(initializer);
        Py_DECREF(condition);
        throw;
      }
    } else if (increment_expression_ctx) {
      try {
        increment = visitAsPyObject(increment_expression_ctx);
      } catch (...) {
        Py_DECREF(initializer);
        Py_DECREF(condition);
        throw;
      }
    } else {
      increment = Py_None;
      Py_INCREF(increment);
    }

    PyObject* body;
    try {
      body = visitAsPyObject(ctx->statement());
    } catch (...) {
      Py_DECREF(initializer);
      Py_DECREF(condition);
      Py_DECREF(increment);
      throw;
    }

    PyObject* ret = build_ast_node(
        "ForStatement", "{s:N,s:N,s:N,s:N}", "initializer", initializer, "condition", condition, "increment", increment,
        "body", body
    );
    if (!ret) {
      Py_DECREF(initializer);
      Py_DECREF(condition);
      Py_DECREF(increment);
      Py_DECREF(body);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(FuncStmt) {
    string name = visitAsString(ctx->identifier());
    PyObject* params;
    auto identifier_list_ctx = ctx->identifierList();
    if (identifier_list_ctx) {
      params = visitAsPyObject(identifier_list_ctx);
    } else {
      params = PyList_New(0);
      if (!params) {
        throw PyInternalError();
      }
    }

    PyObject* body;
    try {
      body = visitAsPyObject(ctx->block());
    } catch (...) {
      Py_DECREF(params);
      throw;
    }

    PyObject* ret = build_ast_node("Function", "{s:s#,s:N,s:N}", "name", name.data(), name.size(), "params", params, "body", body);
    if (!ret) {
      Py_DECREF(params);
      Py_DECREF(body);
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(KvPairList) {
    return visitPyListOfObjects(ctx->kvPair());
  }

  VISIT(KvPair) {
    PyObject* k = visitAsPyObject(ctx->expression(0));
    PyObject* v;
    try {
      v = visitAsPyObject(ctx->expression(1));
    } catch (...) {
      Py_DECREF(k);
      throw;
    }
    PyObject* ret = PyTuple_Pack(2, k, v);
    Py_DECREF(k);
    Py_DECREF(v);
    if (!ret) {
      throw PyInternalError();
    }
    return ret;
  }

  VISIT(IdentifierList) {
	vector<string> identifiers = visitAsVectorOfStrings(ctx->identifier());
    PyObject* ret = X_PyList_FromStrings(identifiers);
    if (!ret) {
        throw PyInternalError();
    }
    return ret;
  }

  VISIT(EmptyStmt) {
    RETURN_NEW_AST_NODE("ExprStatement", "{s:O}", "expr", Py_None);
  }

  VISIT(Block) {
    PyObject* declarations = PyList_New(0);
    if (!declarations) {
      throw PyInternalError();
    }
    auto declaration_ctxs = ctx->declaration();
    for (auto declaration_ctx : declaration_ctxs) {
      if (!declaration_ctx->statement() || !declaration_ctx->statement()->emptyStmt()) {
        PyObject* statement;
        try {
          statement = visitAsPyObject(declaration_ctx);
        } catch (...) {
          Py_DECREF(declarations);
          throw;
        }
        int append_code = PyList_Append(declarations, statement);
        Py_DECREF(statement);
        if (append_code == -1) {
          Py_DECREF(declarations);
          throw PyInternalError();
        }
      }
    }
    PyObject* ret = build_ast_node("Block", "{s:N}", "declarations", declarations);
    if (!ret) {
      Py_DECREF(declarations);
      throw PyInternalError();
    }
    return ret;
  }

  // HogQL rules

  VISIT(Select) {
    auto select_union_stmt_ctx = ctx->selectUnionStmt();
    if (select_union_stmt_ctx) {
      return visit(select_union_stmt_ctx);
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
      return visitAsPyObject(placeholder_ctx);
    }

    return visit(ctx->selectUnionStmt());
  }

  VISIT(SelectUnionStmt) {
    // Using a vector of PyObjects atypically here, because this is a precursor of flattened_queries
    vector<PyObject*> select_queries;
    auto select_stmt_with_parens_ctxs = ctx->selectStmtWithParens();
    select_queries.reserve(select_stmt_with_parens_ctxs.size());
    for (auto select_stmt_with_parens_ctx : select_stmt_with_parens_ctxs) {
      try {
        select_queries.push_back(visitAsPyObject(select_stmt_with_parens_ctx));
      } catch (...) {
        X_Py_DECREF_ALL(select_queries);
        throw;
      }
    }
    PyObject* flattened_queries = PyList_New(0);
    if (!flattened_queries) {
      X_Py_DECREF_ALL(select_queries);
      throw PyInternalError();
    }
    for (auto query : select_queries) {
      int is_select_query = is_ast_node_instance(query, "SelectQuery");
      if (is_select_query == -1) goto select_queries_loop_py_error;
      if (is_ast_node_instance(query, "SelectQuery")) {
        int append_code = PyList_Append(flattened_queries, query);
        if (append_code == -1) goto select_queries_loop_py_error;
      } else if (is_ast_node_instance(query, "SelectUnionQuery")) {
        // Extend flattened_queries with sub_select_queries
        PyObject* sub_select_queries = PyObject_GetAttrString(query, "select_queries");
        if (!sub_select_queries) goto select_queries_loop_py_error;
        int extend_code = X_PyList_Extend(flattened_queries, sub_select_queries);
        if (extend_code == -1) goto select_queries_loop_py_error;
        Py_DECREF(sub_select_queries);
      } else if (is_ast_node_instance(query, "Placeholder")) {
        int append_code = PyList_Append(flattened_queries, query);
        if (append_code == -1) goto select_queries_loop_py_error;
      } else {
        Py_DECREF(flattened_queries);
        X_Py_DECREF_ALL(select_queries);
        throw ParsingError("Unexpected query node type: " + string(Py_TYPE(query)->tp_name));
      }
    }
    goto select_queries_loop_success;
  select_queries_loop_py_error:
    X_Py_DECREF_ALL(select_queries);
    Py_DECREF(flattened_queries);
    throw PyInternalError();
  select_queries_loop_success:
    X_Py_DECREF_ALL(select_queries);
    Py_ssize_t flattened_queries_size = PyList_Size(flattened_queries);
    if (flattened_queries_size == -1) {
      Py_DECREF(flattened_queries);
      throw PyInternalError();
    }
    if (flattened_queries_size == 1) {
      PyObject* query = PyList_GET_ITEM(flattened_queries, 0);
      Py_INCREF(query);
      Py_DECREF(flattened_queries);
      return query;
    }
    RETURN_NEW_AST_NODE("SelectUnionQuery", "{s:N}", "select_queries", flattened_queries);
  }

  VISIT(SelectStmt) {
    // These are stolen by select_query
    PyObject *ctes = NULL, *select = NULL, *select_from = NULL, *where = NULL, *prewhere = NULL, *having = NULL,
             *group_by = NULL, *order_by = NULL;

    try {
      ctes = visitAsPyObjectOrNone(ctx->withClause());
      select = visitAsPyObjectOrEmptyList(ctx->columnExprList());
      select_from = visitAsPyObjectOrNone(ctx->fromClause());
      where = visitAsPyObjectOrNone(ctx->whereClause());
      prewhere = visitAsPyObjectOrNone(ctx->prewhereClause());
      having = visitAsPyObjectOrNone(ctx->havingClause());
      group_by = visitAsPyObjectOrNone(ctx->groupByClause());
      order_by = visitAsPyObjectOrNone(ctx->orderByClause());
    } catch (...) {
      Py_XDECREF(ctes);
      Py_XDECREF(select);
      Py_XDECREF(select_from);
      Py_XDECREF(where);
      Py_XDECREF(prewhere);
      Py_XDECREF(having);
      Py_XDECREF(group_by);
      Py_XDECREF(order_by);
      throw;
    }

    PyObject* select_query = build_ast_node(
        "SelectQuery", "{s:N,s:N,s:N,s:N,s:N,s:N,s:N,s:N,s:N}", "ctes", ctes, "select", select, "distinct",
        Py_NewRef(ctx->DISTINCT() ? Py_True : Py_None), "select_from", select_from, "where", where, "prewhere",
        prewhere, "having", having, "group_by", group_by, "order_by", order_by
    );
    if (!select_query) {
      throw PyInternalError();
    }

    int err_indicator = 0;

    auto window_clause_ctx = ctx->windowClause();
    if (window_clause_ctx) {
      auto window_expr_ctxs = window_clause_ctx->windowExpr();
      auto identifier_ctxs = window_clause_ctx->identifier();
      if (window_expr_ctxs.size() != identifier_ctxs.size()) {
        Py_DECREF(select_query);
        throw ParsingError("WindowClause must have a matching number of window exprs and identifiers");
      }
      PyObject* window_exprs = PyDict_New();
      if (!window_exprs) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }
      for (size_t i = 0; i < window_expr_ctxs.size(); i++) {
        string identifier;
        PyObject* window_expr;
        try {
          identifier = visitAsString(identifier_ctxs[i]);
          window_expr = visitAsPyObject(window_expr_ctxs[i]);
        } catch (...) {
          Py_DECREF(window_exprs);
          Py_DECREF(select_query);
          throw;
        }
        err_indicator = PyDict_SetItemString(window_exprs, identifier.c_str(), window_expr);
        Py_DECREF(window_expr);
        if (err_indicator == -1) {
          Py_DECREF(window_exprs);
          Py_DECREF(select_query);
          throw PyInternalError();
        }
      }
      err_indicator = PyObject_SetAttrString(select_query, "window_exprs", window_exprs);
      Py_DECREF(window_exprs);
      if (err_indicator == -1) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }
    }

    auto limit_and_offset_clause_ctx = ctx->limitAndOffsetClause();
    if (limit_and_offset_clause_ctx) {
      PyObject* limit;
      try {
        limit = visitAsPyObject(limit_and_offset_clause_ctx->columnExpr(0));
      } catch (...) {
        Py_DECREF(select_query);
        throw;
      }
      err_indicator = PyObject_SetAttrString(select_query, "limit", limit);
      Py_DECREF(limit);
      if (err_indicator == -1) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }
      auto offset_ctx = limit_and_offset_clause_ctx->columnExpr(1);
      if (offset_ctx) {
        PyObject* offset;
        try {
          offset = visitAsPyObject(offset_ctx);
        } catch (...) {
          Py_DECREF(select_query);
          throw;
        }
        err_indicator = PyObject_SetAttrString(select_query, "offset", offset);
        Py_DECREF(offset);
        if (err_indicator == -1) {
          Py_DECREF(select_query);
          throw PyInternalError();
        }
      }
      auto limit_by_exprs_ctx = limit_and_offset_clause_ctx->columnExprList();
      if (limit_by_exprs_ctx) {
        PyObject* limit_by_exprs;
        try {
          limit_by_exprs = visitAsPyObject(limit_by_exprs_ctx);
        } catch (...) {
          Py_DECREF(select_query);
          throw;
        }
        err_indicator = PyObject_SetAttrString(select_query, "limit_by", limit_by_exprs);
        Py_DECREF(limit_by_exprs);
        if (err_indicator == -1) {
          Py_DECREF(select_query);
          throw PyInternalError();
        }
      }
      if (limit_and_offset_clause_ctx->WITH() && limit_and_offset_clause_ctx->TIES()) {
        err_indicator = PyObject_SetAttrString(select_query, "limit_with_ties", Py_True);
        if (err_indicator == -1) {
          Py_DECREF(select_query);
          throw PyInternalError();
        }
      }
    } else {
      auto offset_only_clause_ctx = ctx->offsetOnlyClause();
      if (offset_only_clause_ctx) {
        PyObject* offset_only_clause;
        try {
          offset_only_clause = visitAsPyObject(offset_only_clause_ctx->columnExpr());
        } catch (...) {
          Py_DECREF(select_query);
          throw;
        }
        err_indicator = PyObject_SetAttrString(select_query, "offset", offset_only_clause);
        Py_DECREF(offset_only_clause);
        if (err_indicator == -1) {
          Py_DECREF(select_query);
          throw PyInternalError();
        }
      }
    }

    auto array_join_clause_ctx = ctx->arrayJoinClause();
    if (array_join_clause_ctx) {
      if (Py_IsNone(select_from)) {
        Py_DECREF(select_query);
        throw SyntaxError("Using ARRAY JOIN without a FROM clause is not permitted");
      }
      PyObject* join_op = PyUnicode_FromString(
          array_join_clause_ctx->LEFT()    ? "LEFT ARRAY JOIN"
          : array_join_clause_ctx->INNER() ? "INNER ARRAY JOIN"
                                           : "ARRAY JOIN"
      );
      if (!join_op) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }
      err_indicator = PyObject_SetAttrString(select_query, "array_join_op", join_op);
      Py_DECREF(join_op);
      if (err_indicator == -1) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }

      auto array_join_arrays_ctx = array_join_clause_ctx->columnExprList();
      PyObject* array_join_list;
      try {
        array_join_list = visitAsPyObject(array_join_arrays_ctx);
      } catch (...) {
        Py_DECREF(select_query);
        throw;
      }
      Py_ssize_t array_join_list_size = PyList_Size(array_join_list);
      if (array_join_list_size == -1) {
        Py_DECREF(select_query);
        Py_DECREF(array_join_list);
        throw PyInternalError();
      }
      for (Py_ssize_t i = 0; i < array_join_list_size; i++) {
        PyObject* expr = PyList_GET_ITEM(array_join_list, i);
        int is_alias = is_ast_node_instance(expr, "Alias");
        if (is_alias == -1) {
          Py_DECREF(array_join_list);
          Py_DECREF(select_query);
          throw PyInternalError();
        }
        if (!is_alias) {
          Py_DECREF(array_join_list);
          Py_DECREF(select_query);
          auto relevant_column_expr_ctx = array_join_arrays_ctx->columnExpr(i);
          throw SyntaxError(
              "ARRAY JOIN arrays must have an alias", relevant_column_expr_ctx->getStart()->getStartIndex(),
              relevant_column_expr_ctx->getStop()->getStopIndex() + 1
          );
        }
      }
      err_indicator = PyObject_SetAttrString(select_query, "array_join_list", array_join_list);
      Py_DECREF(array_join_list);
      if (err_indicator == -1) {
        Py_DECREF(select_query);
        throw PyInternalError();
      }
    }

    if (ctx->topClause()) {
      Py_DECREF(select_query);
      throw NotImplementedError("Unsupported: SelectStmt.topClause()");
    }
    if (ctx->settingsClause()) {
      Py_DECREF(select_query);
      throw NotImplementedError("Unsupported: SelectStmt.settingsClause()");
    }

    return select_query;
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

  VISIT_UNSUPPORTED(ProjectionOrderByClause)

  VISIT_UNSUPPORTED(LimitAndOffsetClause)

  VISIT_UNSUPPORTED(SettingsClause)

#define RETURN_CHAINED_JOIN_EXPRS()                                                                              \
  PyObject* last_join = join1;                                                                                   \
  PyObject* next_join =                                                                                          \
      PyObject_GetAttrString(last_join, "next_join"); /* 1500 is Python's recursion limit (C_RECURSION_LIMIT) */ \
  for (size_t i = 0; i < 1500; i++) { /* We can safely decref, because a reference is anyway held by join1 */    \
    Py_XDECREF(next_join);                                                                                       \
    if (!next_join) {                                                                                            \
      Py_DECREF(join1);                                                                                          \
      Py_DECREF(join2);                                                                                          \
      throw PyInternalError();                                                                               \
    }                                                                                                            \
    int reached_end_of_chain = Py_IsNone(next_join);                                                             \
    if (reached_end_of_chain == -1) {                                                                            \
      Py_DECREF(join1);                                                                                          \
      Py_DECREF(join2);                                                                                          \
      throw PyInternalError();                                                                               \
    }                                                                                                            \
    if (reached_end_of_chain) {                                                                                  \
      int err_indicator = PyObject_SetAttrString(last_join, "next_join", join2);                                 \
      if (err_indicator == -1) {                                                                                 \
        Py_DECREF(join1);                                                                                        \
        Py_DECREF(join2);                                                                                        \
        throw PyInternalError();                                                                             \
      }                                                                                                          \
      Py_DECREF(join2);                                                                                          \
      return join1;                                                                                              \
    }                                                                                                            \
    last_join = next_join;                                                                                       \
    next_join = PyObject_GetAttrString(last_join, "next_join");                                                  \
  }                                                                                                              \
  Py_DECREF(join1);                                                                                              \
  Py_DECREF(join2);                                                                                              \
  PyErr_SetString(PyExc_RecursionError, "maximum recursion depth exceeded during JOIN parsing");                 \
  throw PyInternalError(); /* This should never be reached, but `while (true)`s are scary, so better to be safe */

  VISIT(JoinExprOp) {
    auto join_op_ctx = ctx->joinOp();
    PyObject* py_join_op;
    if (join_op_ctx) {
      string join_op = visitAsString(join_op_ctx);
      join_op.append(" JOIN");
      py_join_op = PyUnicode_FromStringAndSize(join_op.data(), join_op.size());
    } else {
      py_join_op = PyUnicode_FromString("JOIN");
    }
    if (!py_join_op) throw PyInternalError();

    int err_indicator = 0;

    PyObject* join2;
    try {
      join2 = visitAsPyObject(ctx->joinExpr(1));
    } catch (...) {
      Py_DECREF(py_join_op);
      throw;
    }
    err_indicator = PyObject_SetAttrString(join2, "join_type", py_join_op);
    Py_DECREF(py_join_op);
    if (err_indicator == -1) {
      Py_DECREF(join2);
      throw PyInternalError();
    }
    PyObject* constraint;
    try {
      constraint = visitAsPyObject(ctx->joinConstraintClause());
    } catch (...) {
      Py_DECREF(join2);
      throw;
    }
    err_indicator = PyObject_SetAttrString(join2, "constraint", constraint);
    Py_DECREF(constraint);
    if (err_indicator == -1) {
      Py_DECREF(join2);
      throw PyInternalError();
    }

    PyObject* join1;
    try {
      join1 = visitAsPyObject(ctx->joinExpr(0));
    } catch (...) {
      Py_DECREF(join2);
      throw;
    }

    RETURN_CHAINED_JOIN_EXPRS();
  }

  VISIT(JoinExprTable) {
    PyObject* table = visitAsPyObject(ctx->tableExpr());
    int is_table_join_expr = is_ast_node_instance(table, "JoinExpr");
    if (is_table_join_expr == -1) {
      Py_DECREF(table);
      throw PyInternalError();
    }
    PyObject* sample;
    try {
      sample = visitAsPyObjectOrNone(ctx->sampleClause());
    } catch (...) {
      Py_DECREF(table);
      throw;
    }
    PyObject* table_final = ctx->FINAL() ? Py_True : Py_None;
    if (is_table_join_expr) {
      int err_indicator = 0;
      err_indicator = PyObject_SetAttrString(table, "sample", sample);
      Py_DECREF(sample);
      if (err_indicator == -1) {
        Py_DECREF(table);
        throw PyInternalError();
      }
      err_indicator = PyObject_SetAttrString(table, "table_final", table_final);
      if (err_indicator == -1) {
        Py_DECREF(table);
        throw PyInternalError();
      }
      return table;
    } else {
      PyObject* ret =
          build_ast_node("JoinExpr", "{s:N,s:O,s:N}", "table", table, "table_final", table_final, "sample", sample);
      if (!ret) {
        Py_DECREF(table);
        Py_DECREF(sample);
        throw PyInternalError();
      }
      return ret;
    }
  }

  VISIT(JoinExprParens) { return visit(ctx->joinExpr()); }

  VISIT(JoinExprCrossOp) {
    PyObject* join_type = PyUnicode_FromString("CROSS JOIN");
    if (!join_type) {
      throw PyInternalError();
    }

    PyObject* join2;
    try {
      join2 = visitAsPyObject(ctx->joinExpr(1));
    } catch (...) {
      Py_DECREF(join_type);
      throw;
    }
    int err_indicator = PyObject_SetAttrString(join2, "join_type", join_type);
    if (err_indicator == -1) {
      Py_DECREF(join2);
      throw PyInternalError();
    }
    Py_DECREF(join_type);

    PyObject* join1;
    try {
      join1 = visitAsPyObject(ctx->joinExpr(0));
    } catch (...) {
      Py_DECREF(join2);
      throw;
    }

    RETURN_CHAINED_JOIN_EXPRS();
  }

#undef RETURN_CHAINED_JOIN_EXPRS

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
    PyObject* column_expr_list = visitAsPyObject(ctx->columnExprList());
    Py_ssize_t column_expr_list_size = PyList_Size(column_expr_list);
    if (column_expr_list_size == -1) {
      Py_DECREF(column_expr_list);
      throw PyInternalError();
    }
    if (column_expr_list_size > 1) {
      Py_DECREF(column_expr_list);
      throw NotImplementedError("Unsupported: JOIN ... ON with multiple expressions");
    }
    PyObject* expr = Py_NewRef(PyList_GET_ITEM(column_expr_list, 0));
    Py_DECREF(column_expr_list);
    RETURN_NEW_AST_NODE("JoinConstraint", "{s:N,s:s}", "expr", expr, "constraint_type", ctx->USING() ? "USING" : "ON");
  }

  VISIT(SampleClause) {
    PyObject* sample_ratio_expr = visitAsPyObject(ctx->ratioExpr(0));
    PyObject* offset_ratio_expr;
    try {
      offset_ratio_expr = visitAsPyObjectOrNone(ctx->ratioExpr(1));
    } catch (...) {
      Py_DECREF(sample_ratio_expr);
      throw;
    }
    RETURN_NEW_AST_NODE(
        "SampleExpr", "{s:N,s:N}", "sample_value", sample_ratio_expr, "offset_value", offset_ratio_expr
    );
  }

  VISIT(OrderExprList) { return visitPyListOfObjects(ctx->orderExpr()); }

  VISIT(OrderExpr) {
    const char* order = ctx->DESC() || ctx->DESCENDING() ? "DESC" : "ASC";
    RETURN_NEW_AST_NODE("OrderExpr", "{s:N,s:s}", "expr", visitAsPyObject(ctx->columnExpr()), "order", order);
  }

  VISIT(RatioExpr) {
    auto placeholder_ctx = ctx->placeholder();
    if (placeholder_ctx) {
      return visitAsPyObject(placeholder_ctx);
    }

    auto number_literal_ctxs = ctx->numberLiteral();

    if (number_literal_ctxs.size() > 2) {
      throw ParsingError("RatioExpr must have at most two number literals");
    } else if (number_literal_ctxs.size() == 0) {
      throw ParsingError("RatioExpr must have at least one number literal");
    }

    auto left_ctx = number_literal_ctxs[0];
    auto right_ctx = ctx->SLASH() && number_literal_ctxs.size() > 1 ? number_literal_ctxs[1] : NULL;

    PyObject* left = visitAsPyObject(left_ctx);
    PyObject* right;
    try {
      right = visitAsPyObjectOrNone(right_ctx);
    } catch (...) {
      Py_DECREF(left);
      throw;
    }

    RETURN_NEW_AST_NODE("RatioExpr", "{s:N,s:N}", "left", left, "right", right);
  }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  VISIT(WindowExpr) {
    auto frame_ctx = ctx->winFrameClause();
    PyObject* frame = visitAsPyObjectOrNone(frame_ctx);
    int is_frame_a_tuple = PyTuple_Check(frame);
    if (is_frame_a_tuple == -1) {
      Py_DECREF(frame);
      throw PyInternalError();
    }
    if (is_frame_a_tuple) {
      Py_ssize_t frame_tuple_size = PyTuple_Size(frame);
      if (frame_tuple_size == -1) {
        Py_DECREF(frame);
        throw PyInternalError();
      }
      if (frame_tuple_size != 2) {
        Py_DECREF(frame);
        throw ParsingError("WindowExpr frame must be a tuple of size 2");
      }
    }
    PyObject* frame_start = Py_NewRef(is_frame_a_tuple ? PyTuple_GET_ITEM(frame, 0) : frame);
    PyObject* frame_end = Py_NewRef(is_frame_a_tuple ? PyTuple_GET_ITEM(frame, 1) : Py_None);
    Py_DECREF(frame);
    PyObject* frame_method = frame_ctx && frame_ctx->RANGE()  ? PyUnicode_FromString("RANGE")
                             : frame_ctx && frame_ctx->ROWS() ? PyUnicode_FromString("ROWS")
                                                              : Py_NewRef(Py_None);
    if (!frame_method) {
      Py_DECREF(frame_start);
      Py_DECREF(frame_end);
      throw PyInternalError();
    }
    PyObject* partition_by;
    try {
      partition_by = visitAsPyObjectOrNone(ctx->winPartitionByClause());
    } catch (...) {
      Py_DECREF(frame_start);
      Py_DECREF(frame_end);
      Py_DECREF(frame_method);
      throw;
    }

    PyObject* order_by;
    try {
      order_by = visitAsPyObjectOrNone(ctx->winOrderByClause());
    } catch (...) {
      Py_DECREF(frame_start);
      Py_DECREF(frame_end);
      Py_DECREF(frame_method);
      Py_DECREF(partition_by);
      throw;
    }

    RETURN_NEW_AST_NODE(
        "WindowExpr", "{s:N,s:N,s:N,s:N,s:N}", "partition_by", partition_by, "order_by", order_by, "frame_method",
        frame_method, "frame_start", frame_start, "frame_end", frame_end
    );
  }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  VISIT(FrameBetween) {
    PyObject* min = visitAsPyObject(ctx->winFrameBound(0));
    PyObject* max;
    try {
      max = visitAsPyObject(ctx->winFrameBound(1));
    } catch (...) {
      Py_DECREF(min);
      throw;
    }
    return Py_BuildValue("NN", min, max);
  }

  VISIT(WinFrameBound) {
    if (ctx->PRECEDING() || ctx->FOLLOWING()) {
      PyObject* number;
      if (ctx->numberLiteral()) {
        PyObject* constant = visitAsPyObject(ctx->numberLiteral());
        number = PyObject_GetAttrString(constant, "value");
        Py_DECREF(constant);
        if (!number) throw PyInternalError();
      } else {
        number = Py_NewRef(Py_None);
      }
      RETURN_NEW_AST_NODE(
          "WindowFrameExpr", "{s:s,s:N}", "frame_type", ctx->PRECEDING() ? "PRECEDING" : "FOLLOWING", "frame_value",
          number
      );
    } else {
      RETURN_NEW_AST_NODE("WindowFrameExpr", "{s:s}", "frame_type", "CURRENT ROW");
    }
  }

  VISIT(Expr) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnTypeExprSimple)

  VISIT_UNSUPPORTED(ColumnTypeExprNested)

  VISIT_UNSUPPORTED(ColumnTypeExprEnum)

  VISIT_UNSUPPORTED(ColumnTypeExprComplex)

  VISIT_UNSUPPORTED(ColumnTypeExprParam)

  VISIT(ColumnExprList) { return visitPyListOfObjects(ctx->columnExpr()); }

  VISIT(ColumnExprTernaryOp) {
    PyObject* arg_1 = visitAsPyObject(ctx->columnExpr(0));
    PyObject* arg_2;
    try {
      arg_2 = visitAsPyObject(ctx->columnExpr(1));
    } catch (...) {
      Py_DECREF(arg_1);
      throw;
    }
    PyObject* arg_3;
    try {
      arg_3 = visitAsPyObject(ctx->columnExpr(2));
    } catch (...) {
      Py_DECREF(arg_1);
      Py_DECREF(arg_2);
      throw;
    }
    RETURN_NEW_AST_NODE("Call", "{s:s, s:[NNN]}", "name", "if", "args", arg_1, arg_2, arg_3);
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
    PyObject* expr = visitAsPyObject(ctx->columnExpr());

    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), boost::algorithm::to_lower_copy(alias)) !=
        RESERVED_KEYWORDS.end()) {
      Py_DECREF(expr);
      throw SyntaxError("\"" + alias + "\" cannot be an alias or identifier, as it's a reserved keyword");
    }

    RETURN_NEW_AST_NODE("Alias", "{s:N,s:s#}", "expr", expr, "alias", alias.data(), alias.size());
  }

  VISIT(ColumnExprNegate) {
    PyObject* left = build_ast_node("Constant", "{s:i}", "value", 0);
    if (!left) throw PyInternalError();
    PyObject* op = get_ast_enum_member("ArithmeticOperationOp", "Sub");
    if (!op) {
      Py_DECREF(left);
      throw PyInternalError();
    }
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->columnExpr());
    } catch (...) {
      Py_DECREF(op);
      Py_DECREF(left);
      throw;
    }

    RETURN_NEW_AST_NODE("ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
  }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectUnionStmt()); }

  VISIT(ColumnExprArray) {
    RETURN_NEW_AST_NODE("Array", "{s:N}", "exprs", visitAsPyObjectOrEmptyList(ctx->columnExprList()));
  }

  VISIT(ColumnExprDict) {
    RETURN_NEW_AST_NODE("Dict", "{s:N}", "items", visitAsPyObjectOrEmptyList(ctx->kvPairList()));
  }

  VISIT_UNSUPPORTED(ColumnExprSubstring)

  VISIT_UNSUPPORTED(ColumnExprCast)

  VISIT(ColumnExprPrecedence1) {
    PyObject* op;
    if (ctx->SLASH()) {
      op = get_ast_enum_member("ArithmeticOperationOp", "Div");
    } else if (ctx->ASTERISK()) {
      op = get_ast_enum_member("ArithmeticOperationOp", "Mult");
    } else if (ctx->PERCENT()) {
      op = get_ast_enum_member("ArithmeticOperationOp", "Mod");
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence1");
    }
    if (!op) throw PyInternalError();
    PyObject* left;
    try {
      left = visitAsPyObject(ctx->columnExpr(0));
    } catch (...) {
      Py_DECREF(op);
      throw;
    }
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->right);
    } catch (...) {
      Py_DECREF(op);
      Py_DECREF(left);
      throw;
    }
    RETURN_NEW_AST_NODE("ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
  }

  VISIT(ColumnExprPrecedence2) {
    PyObject* left = visitAsPyObject(ctx->left);
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->right);
    } catch (...) {
      Py_DECREF(left);
      throw;
    }

    if (ctx->PLUS()) {
      PyObject* op = get_ast_enum_member("ArithmeticOperationOp", "Add");
      if (!op) {
        Py_DECREF(left);
        Py_DECREF(right);
        throw PyInternalError();
      }
      RETURN_NEW_AST_NODE("ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
    } else if (ctx->DASH()) {
      PyObject* op = get_ast_enum_member("ArithmeticOperationOp", "Sub");
      if (!op) {
        Py_DECREF(left);
        Py_DECREF(right);
        throw PyInternalError();
      }
      RETURN_NEW_AST_NODE("ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
    } else if (ctx->CONCAT()) {
#define IS_NODE_A_CONCAT_CALL(VAR) /* This is complex because of all the error handling, hence a macro */ \
  int is_##VAR##_a_concat_call = false;                                                                   \
  int is_##VAR##_a_call = is_ast_node_instance(VAR, "Call");                                              \
  if (is_##VAR##_a_call == -1) {                                                                          \
    Py_DECREF(left);                                                                                      \
    Py_DECREF(right);                                                                                     \
    throw PyInternalError();                                                                          \
  }                                                                                                       \
  if (is_##VAR##_a_call) {                                                                                \
    PyObject* VAR##_name = PyObject_GetAttrString(VAR, "name");                                           \
    if (!VAR##_name) {                                                                                    \
      Py_DECREF(left);                                                                                    \
      Py_DECREF(right);                                                                                   \
      Py_DECREF(concat_as_str);                                                                           \
      throw PyInternalError();                                                                        \
    }                                                                                                     \
    PyObject* VAR##_name_lower = PyObject_CallMethod(VAR##_name, "lower", NULL);                          \
    Py_DECREF(VAR##_name);                                                                                \
    if (!VAR##_name_lower) {                                                                              \
      Py_DECREF(left);                                                                                    \
      Py_DECREF(right);                                                                                   \
      Py_DECREF(concat_as_str);                                                                           \
      throw PyInternalError();                                                                        \
    }                                                                                                     \
    is_##VAR##_a_concat_call = PyObject_RichCompareBool(VAR##_name_lower, concat_as_str, Py_EQ);          \
    Py_DECREF(VAR##_name_lower);                                                                          \
    if (is_##VAR##_a_concat_call == -1) {                                                                 \
      Py_DECREF(left);                                                                                    \
      Py_DECREF(right);                                                                                   \
      Py_DECREF(concat_as_str);                                                                           \
      throw PyInternalError();                                                                        \
    }                                                                                                     \
  }

      PyObject* concat_as_str = PyUnicode_FromString("concat");
      if (!concat_as_str) {
        Py_DECREF(left);
        Py_DECREF(right);
        throw PyInternalError();
      }
      IS_NODE_A_CONCAT_CALL(left);
      IS_NODE_A_CONCAT_CALL(right);
      Py_DECREF(concat_as_str);

#undef IS_NODE_A_CONCAT_CALL

      PyObject* args = is_left_a_concat_call ? PyObject_GetAttrString(left, "args") : Py_BuildValue("[O]", left);
      if (!args) {
        Py_DECREF(left);
        Py_DECREF(right);
        throw PyInternalError();
      }
      if (is_right_a_concat_call) {
        PyObject* right_args = PyObject_GetAttrString(right, "args");
        if (!right_args) {
          Py_DECREF(args);
          Py_DECREF(left);
          Py_DECREF(right);
          throw PyInternalError();
        }
        int err_indicator = X_PyList_Extend(args, right_args);
        Py_DECREF(right_args);
        if (err_indicator == -1) {
          Py_DECREF(args);
          Py_DECREF(left);
          Py_DECREF(right);
          throw PyInternalError();
        }
      } else {
        int err_indicator = PyList_Append(args, right);
        if (err_indicator == -1) {
          Py_DECREF(args);
          Py_DECREF(left);
          Py_DECREF(right);
          throw PyInternalError();
        }
      }
      Py_DECREF(right);
      Py_DECREF(left);
      RETURN_NEW_AST_NODE("Call", "{s:s,s:N}", "name", "concat", "args", args);
    } else {
      Py_DECREF(right);
      Py_DECREF(left);
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence2");
    }
  }

  VISIT(ColumnExprPrecedence3) {
    PyObject* op = NULL;
    if (ctx->EQ_SINGLE() || ctx->EQ_DOUBLE()) {
      op = get_ast_enum_member("CompareOperationOp", "Eq");
    } else if (ctx->NOT_EQ()) {
      op = get_ast_enum_member("CompareOperationOp", "NotEq");
    } else if (ctx->LT()) {
      op = get_ast_enum_member("CompareOperationOp", "Lt");
    } else if (ctx->LT_EQ()) {
      op = get_ast_enum_member("CompareOperationOp", "LtEq");
    } else if (ctx->GT()) {
      op = get_ast_enum_member("CompareOperationOp", "Gt");
    } else if (ctx->GT_EQ()) {
      op = get_ast_enum_member("CompareOperationOp", "GtEq");
    } else if (ctx->LIKE()) {
      if (ctx->NOT()) {
        op = get_ast_enum_member("CompareOperationOp", "NotLike");
      } else {
        op = get_ast_enum_member("CompareOperationOp", "Like");
      }
    } else if (ctx->ILIKE()) {
      if (ctx->NOT()) {
        op = get_ast_enum_member("CompareOperationOp", "NotILike");
      } else {
        op = get_ast_enum_member("CompareOperationOp", "ILike");
      }
    } else if (ctx->REGEX_SINGLE() or ctx->REGEX_DOUBLE()) {
      op = get_ast_enum_member("CompareOperationOp", "Regex");
    } else if (ctx->NOT_REGEX()) {
      op = get_ast_enum_member("CompareOperationOp", "NotRegex");
    } else if (ctx->IREGEX_SINGLE() or ctx->IREGEX_DOUBLE()) {
      op = get_ast_enum_member("CompareOperationOp", "IRegex");
    } else if (ctx->NOT_IREGEX()) {
      op = get_ast_enum_member("CompareOperationOp", "NotIRegex");
    } else if (ctx->IN()) {
      if (ctx->COHORT()) {
        if (ctx->NOT()) {
          op = get_ast_enum_member("CompareOperationOp", "NotInCohort");
        } else {
          op = get_ast_enum_member("CompareOperationOp", "InCohort");
        }
      } else {
        if (ctx->NOT()) {
          op = get_ast_enum_member("CompareOperationOp", "NotIn");
        } else {
          op = get_ast_enum_member("CompareOperationOp", "In");
        }
      }
    } else {
      throw ParsingError("Unsupported value of rule ColumnExprPrecedence3");
    }
    if (!op) throw PyInternalError();

    PyObject* left;
    try {
      left = visitAsPyObject(ctx->left);
    } catch (...) {
      Py_DECREF(op);
      throw;
    }
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->right);
    } catch (...) {
      Py_DECREF(op);
      Py_DECREF(left);
      throw;
    }

    RETURN_NEW_AST_NODE("CompareOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
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

    RETURN_NEW_AST_NODE("Call", "{s:s,s:[N]}", "name", name, "args", visitAsPyObject(ctx->columnExpr()));
  }

  VISIT(ColumnExprIsNull) {
    PyObject* null_constant = build_ast_node("Constant", "{s:O}", "value", Py_None);
    if (!null_constant) throw PyInternalError();
    PyObject* op = get_ast_enum_member("CompareOperationOp", ctx->NOT() ? "NotEq" : "Eq");
    if (!op) {
      Py_DECREF(null_constant);
      throw PyInternalError();
    }
    PyObject* left;
    try {
      left = visitAsPyObject(ctx->columnExpr());
    } catch (...) {
      Py_DECREF(op);
      Py_DECREF(null_constant);
      throw;
    }
    RETURN_NEW_AST_NODE("CompareOperation", "{s:N,s:N,s:N}", "left", left, "right", null_constant, "op", op);
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
    PyObject* expr = visitAsPyObject(ctx->columnExpr());
    PyObject* value = visitAsPyObject(ctx->string());
    if (!value) throw PyInternalError();
    RETURN_NEW_AST_NODE("Call", "{s:s,s:[NN]}", "name", name, "args", expr, value);
  }

  VISIT(ColumnExprTuple) {
    RETURN_NEW_AST_NODE("Tuple", "{s:N}", "exprs", visitAsPyObjectOrEmptyList(ctx->columnExprList()));
  }

  VISIT(ColumnExprArrayAccess) {
    PyObject* property = visitAsPyObject(ctx->columnExpr(1));
    int is_property_a_constant = is_ast_node_instance(property, "Constant");
    if (is_property_a_constant == -1) {
      Py_DECREF(property);
      throw PyInternalError();
    }
    if (is_property_a_constant) {
      PyObject* property_value = PyObject_GetAttrString(property, "value");
      if (!property_value) {
        Py_DECREF(property);
        throw PyInternalError();
      }
      PyObject* zero = PyLong_FromLong(0);
      if (!zero) {
        Py_DECREF(property_value);
        Py_DECREF(property);
        throw PyInternalError();
      }
      int is_property_zero = PyObject_RichCompareBool(property_value, zero, Py_EQ);
      Py_DECREF(zero);
      Py_DECREF(property_value);
      if (is_property_zero == -1) {
        Py_DECREF(property);
        throw PyInternalError();
      }
      if (is_property_zero) {
        Py_DECREF(property);
        throw SyntaxError("SQL indexes start from one, not from zero. E.g: array[1]");
      }
    }
    PyObject* object;
    try {
      object = visitAsPyObject(ctx->columnExpr(0));
    } catch (...) {
      Py_DECREF(property);
      throw;
    }
    RETURN_NEW_AST_NODE("ArrayAccess", "{s:N,s:N}", "array", object, "property", property);
  }

  VISIT(ColumnExprPropertyAccess) {
    string identifier = visitAsString(ctx->identifier());
    PyObject* property = build_ast_node("Constant", "{s:s#}", "value", identifier.data(), identifier.size());
    if (!property) {
      throw PyInternalError();
    }
    PyObject* object;
    try {
      object = visitAsPyObject(ctx->columnExpr());
    } catch (...) {
      Py_DECREF(property);
      throw;
    }
    RETURN_NEW_AST_NODE("ArrayAccess", "{s:N,s:N}", "array", object, "property", property);
  }

  VISIT_UNSUPPORTED(ColumnExprBetween)

  VISIT(ColumnExprParens) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnExprTimestamp)

  VISIT(ColumnExprAnd) {
    PyObject* left = visitAsPyObject(ctx->columnExpr(0));
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->columnExpr(1));
    } catch (...) {
      Py_DECREF(left);
      throw;
    }

    int is_left_an_and = is_ast_node_instance(left, "And");
    if (is_left_an_and == -1) {
      Py_DECREF(left);
      Py_DECREF(right);
      throw PyInternalError();
    }
    PyObject* exprs = is_left_an_and ? PyObject_GetAttrString(left, "exprs") : Py_BuildValue("[O]", left);

    int is_right_an_and = is_ast_node_instance(right, "And");
    if (is_right_an_and == -1) goto right_check_error;
    if (is_right_an_and) {
      PyObject* right_exprs = PyObject_GetAttrString(right, "exprs");
      if (!right_exprs) goto right_check_error;
      int err_indicator = X_PyList_Extend(exprs, right_exprs);
      Py_DECREF(right_exprs);
      if (err_indicator == -1) goto right_check_error;
    } else {
      int err_indicator = PyList_Append(exprs, right);
      if (err_indicator == -1) goto right_check_error;
    }
    goto right_check_success;
  right_check_error:
    Py_DECREF(exprs);
    Py_DECREF(left);
    Py_DECREF(right);
    throw PyInternalError();
  right_check_success:
    Py_DECREF(right);
    Py_DECREF(left);

    RETURN_NEW_AST_NODE("And", "{s:N}", "exprs", exprs);
  }

  VISIT(ColumnExprOr) {
    PyObject* left = visitAsPyObject(ctx->columnExpr(0));
    PyObject* right;
    try {
      right = visitAsPyObject(ctx->columnExpr(1));
    } catch (...) {
      Py_DECREF(left);
      throw;
    }

    int is_left_an_or = is_ast_node_instance(left, "Or");
    if (is_left_an_or == -1) {
      Py_DECREF(left);
      Py_DECREF(right);
      throw PyInternalError();
    }
    PyObject* exprs = is_left_an_or ? PyObject_GetAttrString(left, "exprs") : Py_BuildValue("[O]", left);

    int is_right_an_or = is_ast_node_instance(right, "Or");
    if (is_right_an_or == -1) goto right_check_error;
    if (is_right_an_or) {
      PyObject* right_exprs = PyObject_GetAttrString(right, "exprs");
      if (!right_exprs) goto right_check_error;
      int err_indicator = X_PyList_Extend(exprs, right_exprs);
      if (err_indicator == -1) goto right_check_error;
      Py_DECREF(right_exprs);
    } else {
      int err_indicator = PyList_Append(exprs, right);
      if (err_indicator == -1) goto right_check_error;
    }
    goto right_check_success;
  right_check_error:
    Py_DECREF(exprs);
    Py_DECREF(left);
    Py_DECREF(right);
    throw PyInternalError();
  right_check_success:
    Py_DECREF(right);
    Py_DECREF(left);

    RETURN_NEW_AST_NODE("Or", "{s:N}", "exprs", exprs);
  }

  VISIT(ColumnExprTupleAccess) {
    PyObject* index = PyLong_FromString(ctx->DECIMAL_LITERAL()->getText().c_str(), NULL, 10);
    if (!index) throw PyInternalError();
    PyObject* zero = PyLong_FromLong(0);
    if (!zero) {
      Py_DECREF(index);
      throw PyInternalError();
    }
    int is_index_zero = PyObject_RichCompareBool(index, zero, Py_EQ);
    Py_DECREF(zero);
    if (is_index_zero == -1) {
      Py_DECREF(index);
      throw PyInternalError();
    }
    if (is_index_zero) {
      Py_DECREF(index);
      throw SyntaxError("SQL indexes start from one, not from zero. E.g: array[1]");
    }
    PyObject* tuple;
    try {
      tuple = visitAsPyObject(ctx->columnExpr());
    } catch (...) {
      Py_DECREF(index);
      throw;
    }
    RETURN_NEW_AST_NODE("TupleAccess", "{s:N,s:N}", "tuple", tuple, "index", index);
  }

  VISIT(ColumnExprCase) {
    auto column_expr_ctx = ctx->columnExpr();
    size_t columns_size = column_expr_ctx.size();
    PyObject* columns = visitPyListOfObjects(column_expr_ctx);
    if (ctx->caseExpr) {
      PyObject *arg_0 = NULL, *arg_1 = NULL, *arg_2 = NULL, *arg_3 = NULL, *args = NULL;
      PyObject* temp_expr_lists[2] = {NULL, NULL};
      arg_0 = PyList_GET_ITEM(columns, 0);
      arg_1 = build_ast_node("Array", "{s:[]}", "exprs");
      if (!arg_1) goto error;
      arg_2 = build_ast_node("Array", "{s:[]}", "exprs");
      if (!arg_2) goto error;
      arg_3 = PyList_GET_ITEM(columns, columns_size - 1);
      args = Py_BuildValue("[ONNO]", arg_0, arg_1, arg_2, arg_3);
      if (!args) goto error;
      temp_expr_lists[0] = PyObject_GetAttrString(arg_1, "exprs");
      if (!temp_expr_lists[0]) goto error;
      temp_expr_lists[1] = PyObject_GetAttrString(arg_2, "exprs");
      if (!temp_expr_lists[1]) goto error;
      for (size_t index = 1; index < columns_size - 1; index++) {
        PyObject* item = PyList_GetItem(columns, index);
        if (!item) goto error;
        int err_indicator = PyList_Append(temp_expr_lists[(index - 1) % 2], item);
        if (err_indicator == -1) goto error;
      }
      Py_DECREF(temp_expr_lists[1]);
      Py_DECREF(temp_expr_lists[0]);
      Py_DECREF(columns);
      goto success;
    error:
      Py_XDECREF(temp_expr_lists[1]);
      Py_XDECREF(temp_expr_lists[0]);
      Py_XDECREF(args);
      Py_XDECREF(arg_2);
      Py_XDECREF(arg_1);
      Py_XDECREF(columns);
      throw PyInternalError();
    success:
      RETURN_NEW_AST_NODE("Call", "{s:s,s:N}", "name", "transform", "args", args);
    } else {
      RETURN_NEW_AST_NODE("Call", "{s:s,s:N}", "name", columns_size == 3 ? "if" : "multiIf", "args", columns);
    }
  }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) { RETURN_NEW_AST_NODE("Not", "{s:N}", "expr", visitAsPyObject(ctx->columnExpr())); }

  VISIT(ColumnExprWinFunctionTarget) {
    auto column_expr_list_ctx = ctx->columnExprList();
    string name = visitAsString(ctx->identifier(0));
    string over_identifier = visitAsString(ctx->identifier(1));
    PyObject* exprs = visitAsPyObjectOrEmptyList(column_expr_list_ctx);
    PyObject* args;
    try {
      args = visitAsPyObjectOrEmptyList(ctx->columnArgList());
    } catch (...) {
      Py_DECREF(exprs);
      throw;
    }
    RETURN_NEW_AST_NODE(
        "WindowFunction", "{s:s#,s:N,s:N,s:s#}", "name", name.data(), name.size(), "exprs", exprs, "args", args,
        "over_identifier", over_identifier.data(), over_identifier.size()
    );
  }

  VISIT(ColumnExprWinFunction) {
    string identifier = visitAsString(ctx->identifier());
    auto column_expr_list_ctx = ctx->columnExprList();
    PyObject* exprs = visitAsPyObjectOrEmptyList(column_expr_list_ctx);
    PyObject* args;
    try {
      args = visitAsPyObjectOrEmptyList(ctx->columnArgList());
    } catch (...) {
      Py_DECREF(exprs);
      throw;
    }
    PyObject* over_expr;
    try {
      over_expr = visitAsPyObjectOrNone(ctx->windowExpr());
    } catch (...) {
      Py_DECREF(exprs);
      Py_DECREF(args);
      throw;
    }
    RETURN_NEW_AST_NODE(
        "WindowFunction", "{s:s#,s:N,s:N,s:N}", "name", identifier.data(), identifier.size(), "exprs", exprs,
        "args", args, "over_expr", over_expr
    );
  }

  VISIT(ColumnExprIdentifier) { return visit(ctx->columnIdentifier()); }

  VISIT(ColumnExprFunction) {
    string name = visitAsString(ctx->identifier());
    PyObject* params = visitAsPyObjectOrNone(ctx->columnExprList());
    PyObject* args;
    try {
      args = visitAsPyObjectOrEmptyList(ctx->columnArgList());
    } catch (...) {
      Py_DECREF(params);
      throw;
    }
    RETURN_NEW_AST_NODE(
        "Call", "{s:s#,s:N,s:N,s:O}", "name", name.data(), name.size(), "params", params, "args", args, "distinct",
        ctx->DISTINCT() ? Py_True : Py_False
    );
  }

  VISIT(ColumnExprAsterisk) {
    auto table_identifier_ctx = ctx->tableIdentifier();
    if (table_identifier_ctx) {
      vector<string> table = any_cast<vector<string>>(visit(table_identifier_ctx));
      table.push_back("*");
      RETURN_NEW_AST_NODE("Field", "{s:N}", "chain", X_PyList_FromStrings(table));
    }
    RETURN_NEW_AST_NODE("Field", "{s:[s]}", "chain", "*");
  }

  VISIT(ColumnExprTagElement) { return visit(ctx->hogqlxTagElement()); }

  VISIT(ColumnArgList) { return visitPyListOfObjects(ctx->columnArgExpr()); }

  VISIT(ColumnLambdaExpr) {
    PyObject* expr = visitAsPyObject(ctx->columnExpr());
    PyObject* args;
    try {
      args = X_PyList_FromStrings(visitAsVectorOfStrings(ctx->identifier()));
    } catch (...) {
      Py_DECREF(expr);
      throw;
    }
    RETURN_NEW_AST_NODE("Lambda", "{s:N,s:N}", "args", args, "expr", expr);
  }

  VISIT(WithExprList) {
    PyObject* ctes = PyDict_New();
    if (!ctes) throw PyInternalError();
    for (auto with_expr_ctx : ctx->withExpr()) {
      PyObject* cte;
      try {
        cte = visitAsPyObject(with_expr_ctx);
      } catch (...) {
        Py_DECREF(ctes);
        throw;
      }
      PyObject* name = PyObject_GetAttrString(cte, "name");
      if (!name) {
        Py_DECREF(cte);
        Py_DECREF(ctes);
        throw PyInternalError();
      }
      int err_indicator = PyDict_SetItem(ctes, name, cte);
      if (err_indicator == -1) {
        Py_DECREF(name);
        Py_DECREF(cte);
        Py_DECREF(ctes);
        throw PyInternalError();
      }
      Py_DECREF(name);
      Py_DECREF(cte);
    }
    return ctes;
  }

  VISIT(WithExprSubquery) {
    string name = visitAsString(ctx->identifier());
    RETURN_NEW_AST_NODE(
        "CTE", "{s:s#,s:N,s:s}", "name", name.data(), name.size(), "expr", visitAsPyObject(ctx->selectUnionStmt()),
        "cte_type", "subquery"
    );
  }

  VISIT(WithExprColumn) {
    string name = visitAsString(ctx->identifier());
    PyObject* expr = visitAsPyObject(ctx->columnExpr());
    RETURN_NEW_AST_NODE("CTE", "{s:s#,s:N,s:s}", "name", name.data(), name.size(), "expr", expr, "cte_type", "column");
  }

  VISIT(ColumnIdentifier) {
    auto placeholder_ctx = ctx->placeholder();
    if (placeholder_ctx) {
      return visitAsPyObject(placeholder_ctx);
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
        RETURN_NEW_AST_NODE("Constant", "{s:O}", "value", Py_True);
      }
      if (!text.compare("false")) {
        RETURN_NEW_AST_NODE("Constant", "{s:O}", "value", Py_False);
      }
      RETURN_NEW_AST_NODE("Field", "{s:N}", "chain", X_PyList_FromStrings(nested));
    }
    vector<string> table_plus_nested = table;
    table_plus_nested.insert(table_plus_nested.end(), nested.begin(), nested.end());
    RETURN_NEW_AST_NODE("Field", "{s:N}", "chain", X_PyList_FromStrings(table_plus_nested));
  }

  VISIT(NestedIdentifier) { return visitAsVectorOfStrings(ctx->identifier()); }

  VISIT(TableExprIdentifier) {
    vector<string> chain = any_cast<vector<string>>(visit(ctx->tableIdentifier()));
    RETURN_NEW_AST_NODE("Field", "{s:N}", "chain", X_PyList_FromStrings(chain));
  }

  VISIT(TableExprSubquery) { return visit(ctx->selectUnionStmt()); }

  VISIT(TableExprPlaceholder) { return visitAsPyObject(ctx->placeholder()); }

  VISIT(TableExprAlias) {
    auto alias_ctx = ctx->alias();
    string alias = any_cast<string>(alias_ctx ? visit(alias_ctx) : visit(ctx->identifier()));
    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), boost::algorithm::to_lower_copy(alias)) !=
        RESERVED_KEYWORDS.end()) {
      throw SyntaxError("ALIAS is a reserved keyword");
    }
    PyObject* py_alias = PyUnicode_FromStringAndSize(alias.data(), alias.size());
    if (!py_alias) throw PyInternalError();
    PyObject* table;
    try {
      table = visitAsPyObject(ctx->tableExpr());
    } catch (...) {
      Py_DECREF(py_alias);
      throw;
    }

    int is_table_a_join_expr = is_ast_node_instance(table, "JoinExpr");
    if (is_table_a_join_expr == -1) {
      Py_DECREF(py_alias);
      throw PyInternalError();
    }
    if (is_table_a_join_expr) {
      int err_indicator = PyObject_SetAttrString(table, "alias", py_alias);
      Py_DECREF(py_alias);
      if (err_indicator == -1) {
        Py_DECREF(table);
        throw PyInternalError();
      }
      return table;
    }
    RETURN_NEW_AST_NODE("JoinExpr", "{s:N,s:N}", "table", table, "alias", py_alias);
  }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  VISIT(TableExprTag) { return visit(ctx->hogqlxTagElement()); }

  VISIT(TableFunctionExpr) {
    string table_name = visitAsString(ctx->identifier());
    auto table_args_ctx = ctx->tableArgList();
    PyObject* table_args = table_args_ctx ? visitAsPyObject(table_args_ctx) : PyList_New(0);
    if (!table_args) throw PyInternalError();
    PyObject* table = build_ast_node("Field", "{s:[s#]}", "chain", table_name.data(), table_name.size());
    if (!table) {
      Py_DECREF(table_args);
      throw PyInternalError();
    }
    RETURN_NEW_AST_NODE("JoinExpr", "{s:N,s:N}", "table", table, "table_args", table_args);
  }

  VISIT(TableIdentifier) {
    string text = visitAsString(ctx->identifier());
    auto database_identifier_ctx = ctx->databaseIdentifier();
    if (database_identifier_ctx) {
      return vector<string>{visitAsString(database_identifier_ctx), text};
    }
    return vector<string>{text};
  }

  VISIT(TableArgList) { return visitPyListOfObjects(ctx->columnExpr()); }

  VISIT(DatabaseIdentifier) { return visit(ctx->identifier()); }

  VISIT_UNSUPPORTED(FloatingLiteral)

  VISIT(NumberLiteral) {
    string text = ctx->getText();
    boost::algorithm::to_lower(text);
    if (text.find(".") != string::npos || text.find("e") != string::npos || !text.compare("-inf") ||
        !text.compare("inf") || !text.compare("nan")) {
      PyObject* py_text = PyUnicode_FromStringAndSize(text.data(), text.size());
      if (!py_text) throw PyInternalError();
      PyObject* value = PyFloat_FromString(py_text);
      Py_DECREF(py_text);
      if (!value) throw PyInternalError();
      RETURN_NEW_AST_NODE("Constant", "{s:N}", "value", value);
    } else {
      PyObject* value = PyLong_FromString(text.c_str(), NULL, 10);
      if (!value) throw PyInternalError();
      RETURN_NEW_AST_NODE("Constant", "{s:N}", "value", value);
    }
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      RETURN_NEW_AST_NODE("Constant", "{s:O}", "value", Py_None);
    }
    auto string_literal_terminal = ctx->STRING_LITERAL();
    if (string_literal_terminal) {
      string text = parse_string_literal_ctx(string_literal_terminal);
      RETURN_NEW_AST_NODE("Constant", "{s:s#}", "value", text.data(), text.size());
    }
    return visitChildren(ctx);
  }

  VISIT_UNSUPPORTED(Interval)

  VISIT_UNSUPPORTED(Keyword)

  VISIT_UNSUPPORTED(KeywordForAlias)

  VISIT(Alias) {
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

    auto column_expr_ctx = ctx->columnExpr();
    if (column_expr_ctx) {
      RETURN_NEW_AST_NODE(
          "HogQLXAttribute", "{s:s#,s:N}", "name", name.data(), name.size(), "value", visitAsPyObject(column_expr_ctx)
      );
    }

    auto string_ctx = ctx->string();
    if (string_ctx) {
      PyObject* value = visitAsPyObject(string_ctx);
      if (!value) throw PyInternalError();
      RETURN_NEW_AST_NODE("HogQLXAttribute", "{s:s#,s:N}", "name", name.data(), name.size(), "value", value);
    }

    PyObject* value = build_ast_node("Constant", "{s:O}", "value", Py_True);
    if (!value) throw PyInternalError();
    RETURN_NEW_AST_NODE("HogQLXAttribute", "{s:s#,s:N}", "name", name.data(), name.size(), "value", value);
  }

  VISIT(HogqlxTagElementClosed) {
    string kind = visitAsString(ctx->identifier());
    RETURN_NEW_AST_NODE(
        "HogQLXTag", "{s:s#,s:N}", "kind", kind.data(), kind.size(), "attributes",
        visitPyListOfObjects(ctx->hogqlxTagAttribute())
    );
  }

  VISIT(HogqlxTagElementNested) {
    string opening = visitAsString(ctx->identifier(0));
    string closing = visitAsString(ctx->identifier(1));
    if (opening != closing) {
      throw SyntaxError("Opening and closing HogQLX tags must match. Got " + opening + " and " + closing);
    }

    auto tag_element_ctx = ctx->hogqlxTagElement();
    auto tag_attribute_ctx = ctx->hogqlxTagAttribute();
    PyObject* attributes = PyList_New(tag_attribute_ctx.size() + (tag_element_ctx ? 1 : 0));
    if (!attributes) throw PyInternalError();
    bool found_source = false;
    for (size_t i = 0; i < tag_attribute_ctx.size(); i++) {
      PyObject* object;
      try {
        object = visitAsPyObject(tag_attribute_ctx[i]);
      } catch (...) {
        Py_DECREF(attributes);
        throw;
      }
      PyList_SET_ITEM(attributes, i, object);

      PyObject* name = PyObject_GetAttrString(object, "name");
      if (!name) {
        Py_DECREF(attributes);
        throw PyInternalError();
      }
      PyObject* source_as_str = PyUnicode_FromString("source");
      if (!source_as_str) {
        Py_DECREF(name);
        Py_DECREF(attributes);
        throw PyInternalError();
      }
      int tentative_found_source = PyObject_RichCompareBool(name, source_as_str, Py_EQ);
      Py_DECREF(source_as_str);
      Py_DECREF(name);
      if (tentative_found_source == -1) {
        Py_DECREF(attributes);
        throw PyInternalError();
      }
      if (tentative_found_source) {
        found_source = true;
      }
    }

    if (tag_element_ctx) {
      if (found_source) {
        Py_DECREF(attributes);
        throw SyntaxError("Nested HogQLX tags cannot have a source attribute");
      }
      PyObject* source_attribute = build_ast_node(
          "HogQLXAttribute", "{s:s#,s:N}", "name", "source", 6, "value", visitAsPyObject(ctx->hogqlxTagElement())
      );
      if (!source_attribute) {
        Py_DECREF(attributes);
        throw PyInternalError();
      }
      PyList_SET_ITEM(attributes, tag_attribute_ctx.size(), source_attribute);
    }

    RETURN_NEW_AST_NODE("HogQLXTag", "{s:s#,s:N}", "kind", opening.data(), opening.size(), "attributes", attributes);
  }

  VISIT(Placeholder) {
    string name = visitAsString(ctx->identifier());
    RETURN_NEW_AST_NODE("Placeholder", "{s:s#}", "field", name.data(), name.size());
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    PyObject* value = visitAsPyObject(ctx->columnExpr(0));
    PyObject* fallback;
    try {
      fallback = visitAsPyObject(ctx->columnExpr(1));
    } catch (...) {
      Py_DECREF(value);
      throw;
    }
    RETURN_NEW_AST_NODE("Call", "{s:s, s:[NN]}", "name", "ifNull", "args", value, fallback);
  }

  VISIT(ColumnExprTemplateString) { return visit(ctx->templateString()); }

  VISIT(String) {
    auto string_literal = ctx->STRING_LITERAL();
    if (string_literal) {
      string text = parse_string_literal_ctx(string_literal);
      RETURN_NEW_AST_NODE("Constant", "{s:s#}", "value", text.data(), text.size());
    }
    return visit(ctx->templateString());
  }

  VISIT(TemplateString) {
    auto string_contents = ctx->stringContents();

    if (string_contents.size() == 0) {
      string empty = "";
      RETURN_NEW_AST_NODE("Constant", "{s:s}", "value", "");
    }

    if (string_contents.size() == 1) {
      return visit(string_contents[0]);
    }

    PyObject* args = visitPyListOfObjects(string_contents);
    if (!args) throw PyInternalError();
    RETURN_NEW_AST_NODE("Call", "{s:s,s:N}", "name", "concat", "args", args);
  }

  VISIT(FullTemplateString) {
    auto string_contents_full = ctx->stringContentsFull();

    if (string_contents_full.size() == 0) {
      string empty = "";
      RETURN_NEW_AST_NODE("Constant", "{s:s}", "value", "");
    }

    if (string_contents_full.size() == 1) {
      return visit(string_contents_full[0]);
    }

    PyObject* args = visitPyListOfObjects(string_contents_full);
    if (!args) throw PyInternalError();
    RETURN_NEW_AST_NODE("Call", "{s:s,s:N}", "name", "concat", "args", args);
  }

  VISIT(StringContents) {
    auto string_text = ctx->STRING_TEXT();
    if (string_text) {
      string text = parse_string_text_ctx(string_text, true);
      RETURN_NEW_AST_NODE("Constant", "{s:s#}", "value", text.data(), text.size());
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    string empty = "";
    RETURN_NEW_AST_NODE("Constant", "{s:s}", "value", "");
  }

  VISIT(StringContentsFull) {
    auto full_string_text = ctx->FULL_STRING_TEXT();
    if (full_string_text) {
      string text = parse_string_text_ctx(full_string_text, false);
      RETURN_NEW_AST_NODE("Constant", "{s:s#}", "value", text.data(), text.size());
    }
    auto column_expr = ctx->columnExpr();
    if (column_expr) {
      return visit(column_expr);
    }
    string empty = "";
    RETURN_NEW_AST_NODE("Constant", "{s:s}", "value", "");
  }
};

class HogQLErrorListener : public antlr4::BaseErrorListener {
 public:
  string input;

  HogQLErrorListener(string input) : input(input) {}

  void syntaxError(
      antlr4::Recognizer* recognizer,
      antlr4::Token* offendingSymbol,
      size_t line,
      size_t charPositionInLine,
      const string& msg,
      exception_ptr e
  ) override {
    size_t start = getPosition(line, charPositionInLine);
    if (start == string::npos) {
      start = 0;
    }
    throw SyntaxError(msg, start, input.size());
  }

 private:
  size_t getPosition(size_t line, size_t column) {
    size_t linePosition = 0;
    for (size_t i = 0; i < line - 1; i++) {
      size_t endOfLine = input.find("\n", linePosition);
      if (endOfLine == string::npos) {
        return string::npos;
      }
      linePosition = endOfLine + 1;
    }
    return linePosition + column;
  }
};

// MODULE STATE

parser_state* get_module_state(PyObject* module) {
  return static_cast<parser_state*>(PyModule_GetState(module));
}

// MODULE METHODS

#define METHOD_PARSE_NODE(PASCAL_CASE, CAMEL_CASE, SNAKE_CASE)                                                         \
  static PyObject* method_parse_##SNAKE_CASE(PyObject* self, PyObject* args, PyObject* kwargs) {                       \
    parser_state* state = get_module_state(self);                                                                      \
    const char* str;                                                                                                   \
    int internal = 0;                                                                                                  \
    static const char* kwlist[] = {"input", "is_internal", NULL};                                                      \
    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|p", (char**)kwlist, &str, &internal)) {                          \
      return NULL;                                                                                                     \
    }                                                                                                                  \
    auto input_stream = new antlr4::ANTLRInputStream(str, strnlen(str, 65536));                                        \
    auto lexer = new HogQLLexer(input_stream);                                                                         \
    auto stream = new antlr4::CommonTokenStream(lexer);                                                                \
    auto parser = new HogQLParser(stream);                                                                             \
    parser->removeErrorListeners();                                                                                    \
    auto error_listener = new HogQLErrorListener(str);                                                                 \
    parser->addErrorListener(error_listener);                                                                          \
    HogQLParser::PASCAL_CASE##Context* parse_tree;                                                                     \
    try {                                                                                                              \
      parse_tree = parser->CAMEL_CASE();                                                                               \
    } catch HANDLE_HOGQL_ERROR(SyntaxError, delete error_listener; delete parser; delete stream; delete lexer; \
                                   delete input_stream;);                                                              \
    HogQLParseTreeConverter converter = HogQLParseTreeConverter(state, internal == 1);                                 \
    PyObject* result_node = converter.visitAsPyObjectFinal(parse_tree);                                                \
    delete error_listener;                                                                                             \
    delete parser;                                                                                                     \
    delete stream;                                                                                                     \
    delete lexer;                                                                                                      \
    delete input_stream;                                                                                               \
    return result_node;                                                                                                \
  }

METHOD_PARSE_NODE(Expr, expr, expr)
METHOD_PARSE_NODE(OrderExpr, orderExpr, order_expr)
METHOD_PARSE_NODE(Select, select, select)
METHOD_PARSE_NODE(FullTemplateString, fullTemplateString, full_template_string)
METHOD_PARSE_NODE(Program, program, program)

#undef METHOD_PARSE_NODE

static PyObject* method_parse_string_literal_text(PyObject* self, PyObject* args) {
  parser_state* state = get_module_state(self);
  const char* str;
  if (!PyArg_ParseTuple(args, "s", &str)) {
    return NULL;
  }
  string unquoted_string;
  try {
    unquoted_string = parse_string_literal_text(str);
  } catch HANDLE_HOGQL_ERROR(SyntaxError, );
  return PyUnicode_FromStringAndSize(unquoted_string.data(), unquoted_string.size());
}

// MODULE SETUP

static PyMethodDef parser_methods[] = {
    {.ml_name = "parse_expr",
     .ml_meth = (PyCFunction)method_parse_expr,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL expression string into an AST"},
    {.ml_name = "parse_order_expr",
     .ml_meth = (PyCFunction)method_parse_order_expr,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the ORDER BY clause string into an AST"},
    {.ml_name = "parse_select",
     .ml_meth = (PyCFunction)method_parse_select,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL SELECT statement string into an AST"},
    {.ml_name = "parse_full_template_string",
     .ml_meth = (PyCFunction)method_parse_full_template_string,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog template string into an AST"},
    {.ml_name = "parse_program",
     .ml_meth = (PyCFunction)method_parse_program,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse a Hog program into an AST"},
    {.ml_name = "parse_string_literal_text",
     .ml_meth = method_parse_string_literal_text,
     .ml_flags = METH_VARARGS,
     .ml_doc = "Unquote the string (an identifier or a string literal))"},
    {NULL, NULL, 0, NULL}
};

static int parser_modexec(PyObject* module) {
  parser_state* state = get_module_state(module);
  state->ast_module = PyImport_ImportModule("posthog.hogql.ast");
  if (!state->ast_module) {
    return -1;
  }
  state->base_module = PyImport_ImportModule("posthog.hogql.base");
  if (!state->base_module) {
    return -1;
  }
  state->errors_module = PyImport_ImportModule("posthog.hogql.errors");
  if (!state->errors_module) {
    return -1;
  }
  return 0;
}

static PyModuleDef_Slot parser_slots[] = {
    {Py_mod_exec, (void*)parser_modexec},  // If Python were written in C++, then Py_mod_exec would be typed better, but
                                           // because it's in C, it expects a void pointer
    {0, NULL}
};

static int parser_traverse(PyObject* module, visitproc visit, void* arg) {
  parser_state* state = get_module_state(module);
  Py_VISIT(state->ast_module);
  Py_VISIT(state->base_module);
  Py_VISIT(state->errors_module);
  return 0;
}

static int parser_clear(PyObject* module) {
  parser_state* state = get_module_state(module);
  Py_CLEAR(state->ast_module);
  Py_CLEAR(state->base_module);
  Py_CLEAR(state->errors_module);
  return 0;
}

static struct PyModuleDef parser = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "hogql_parser",
    .m_doc = "HogQL parsing",
    .m_size = sizeof(parser_state),
    .m_methods = parser_methods,
    .m_slots = parser_slots,
    .m_traverse = parser_traverse,
    .m_clear = parser_clear,
};

PyMODINIT_FUNC PyInit_hogql_parser(void) {
  return PyModuleDef_Init(&parser);
}
