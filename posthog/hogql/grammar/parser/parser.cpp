#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <boost/algorithm/string.hpp>
#include <format>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "error.h"
#include "parser.h"
#include "string.h"

#define VISIT(RULE) virtual any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                                 \
  VISIT(RULE) {                                                 \
    throw HogQLNotImplementedError("Unsupported rule: " #RULE); \
  }

using namespace std;

// PYTHON UTILS (`X_` stands for "extension")

// Extend `list` with `extension`, in-place.
void X_PyList_Extend(PyObject* list, PyObject* extension) {
  Py_ssize_t list_size = PyList_Size(list);
  Py_ssize_t extension_size = PyList_Size(extension);
  PyList_SetSlice(list, list_size, list_size + extension_size, extension);
}

// PARSING AND AST CONVERSION

// Conventions:
// 1. If any child rule results in an AST node, so must the parent rule - once in Python land, always in Python land.
//    E.g. it doesn't make sense to create a vector of PyObjects*, that should just be a Python list (a new PyObject*).
// 2. Stay out of Python land as long as possible. E.g. avoid using PyObjects* for ints or strings.
// 3. REMEMBER TO Py_DECREF AND Py_INCREF. Otherwise there will be memory leaks or segfaults.
// 4. For Py_None, Py_True, and Py_False, just wrap them in Py_NewRef().
// 5. In Py_BuildValue tend towards use of `N` (which does not increment the refcount) over `O` (which does).
//    That's because we mostly use new values and not borrowed ones - but this is not a hard rule.
// 6. Use the `auto` type for HogQLParser:: and HogQLLexer:: values. Otherwise it's clearer for the type to be explicit.

// To understand how Py_BuildValue, PyArg_ParseTuple, and PyArg_ParseTupleAndKeywords formats work,
// (for instance, what does `s`, `s#`, `i` or `N` mean) read this:
// https://docs.python.org/3/c-api/arg.html

PyObject* vector_to_list_string(const vector<string>& items) {
  PyObject* list = PyList_New(items.size());
  if (!list) {
    return NULL;
  }
  for (size_t i = 0; i < items.size(); i++) {
    PyObject* value = PyUnicode_FromStringAndSize(items[i].c_str(), items[i].size());
    if (!value) {
      Py_DECREF(list);
      return NULL;
    }
    PyList_SET_ITEM(list, i, value);
  }
  return list;
}

class HogQLParseTreeConverter : public HogQLParserBaseVisitor {
 private:
  parser_state* state;

  const vector<string> RESERVED_KEYWORDS = {"select", "from", "where", "as"};

  // Build an AST node of the specified type. Return value: New reference.
  template <typename... Args>
  PyObject* build_ast_node(const char* type_name, const char* kwargs_format, Args... kwargs_items) {
    PyObject* node_type = PyObject_GetAttrString(state->ast_module, type_name);
    if (!node_type) {
      throw HogQLParsingError("AST node type \"" + string(type_name) + "\" does not exist");
    }
    PyObject* args = PyTuple_New(0);
    PyObject* kwargs = Py_BuildValue(kwargs_format, kwargs_items...);
    PyObject* result = PyObject_Call(node_type, args, kwargs);
    Py_DECREF(kwargs);
    Py_DECREF(args);
    Py_DECREF(node_type);
    return result;
  }

  // Return the specified member of the specified enum. Return value: New reference.
  PyObject* get_ast_enum_member(const char* enum_name, const char* enum_member) {
    PyObject* enum_type = PyObject_GetAttrString(state->ast_module, enum_name);
    PyObject* result = PyObject_GetAttrString(enum_type, enum_member);
    Py_DECREF(enum_type);
    return result;
  }

  // Return the specified member of the specified enum. Return value: New reference.
  bool is_ast_node_instance(PyObject* obj, const char* type_name) {
    PyObject* node_type = PyObject_GetAttrString(state->ast_module, type_name);
    bool result = PyObject_IsInstance(obj, node_type);
    Py_DECREF(node_type);
    return result;
  }

 public:
  HogQLParseTreeConverter(parser_state* state) : state(state) {}

  // This is the only method that should be called from outside the class.
  // Convert the parse tree to an AST node result. If an error has occurred in conversion, handle it gracefully.
  PyObject* visitAsPyObjectFinal(antlr4::tree::ParseTree* tree) {
    try {
      return visitAsPyObject(tree);
    } catch (const bad_any_cast& e) {
      PyErr_SetString(PyExc_RuntimeError, "Parsing failed due to bad type casting");
      return NULL;
    } catch (const HogQLSyntaxError& e) {
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "SyntaxException");
      PyErr_SetString(error_type, e.what());
      Py_DECREF(error_type);
      return NULL;
    } catch (const HogQLNotImplementedError& e) {
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "NotImplementedException");
      PyErr_SetString(error_type, e.what());
      Py_DECREF(error_type);
      return NULL;
    } catch (const HogQLParsingError& e) {
      PyObject* error_type = PyObject_GetAttrString(state->errors_module, "ParsingException");
      PyErr_SetString(error_type, e.what());
      Py_DECREF(error_type);
      return NULL;
    }
  }

  PyObject* visitAsPyObject(antlr4::tree::ParseTree* tree) {
    any result = visit(tree);
    PyObject* cast_result = any_cast<PyObject*>(result);
    if (!cast_result) {
      throw runtime_error("Rule resulted in a null PyObject pointer. A Python exception must be set at this point.");
    }
    return cast_result;
  }

  PyObject* visitAsPyObjectOrNone(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      Py_RETURN_NONE;
    }
    return visitAsPyObject(tree);
  }

  PyObject* visitAsPyObjectOrEmptyList(antlr4::tree::ParseTree* tree) {
    if (tree == NULL) {
      return PyList_New(0);
    }
    return visitAsPyObject(tree);
  }

  string visitAsString(antlr4::tree::ParseTree* tree) {
    any result = visit(tree);
    return any_cast<string>(result);
  }

  // T has to be used in place of antlr4::tree::ParseTree* here, because there's no conversion from the child class
  // to its parent within vectors
  template <typename T>
  PyObject* visitPyListOfObjects(vector<T> tree) {
    PyObject* list = PyList_New(tree.size());
    for (size_t i = 0; i < tree.size(); i++) {
      PyList_SET_ITEM(list, i, visitAsPyObject(tree[i]));
    }
    return list;
  }

  VISIT(Select) {
    auto select_union_stmt_ctx = ctx->selectUnionStmt();
    if (select_union_stmt_ctx) {
      return visit(select_union_stmt_ctx);
    }
    return visit(ctx->selectStmt());
  }

  VISIT(SelectUnionStmt) {
    vector<PyObject*> select_queries;
    auto select_stmt_with_parens_ctxs = ctx->selectStmtWithParens();
    select_queries.reserve(select_stmt_with_parens_ctxs.size());
    for (auto select_stmt_with_parens_ctx : select_stmt_with_parens_ctxs) {
      select_queries.push_back(visitAsPyObject(select_stmt_with_parens_ctx));
    }
    PyObject* flattened_queries = PyList_New(0);
    for (auto query : select_queries) {
      if (is_ast_node_instance(query, "SelectQuery")) {
        PyList_Append(flattened_queries, query);
      } else if (is_ast_node_instance(query, "SelectUnionQuery")) {
        // Extend flattened_queries with sub_select_queries
        PyObject* sub_select_queries = PyObject_GetAttrString(query, "select_queries");
        X_PyList_Extend(flattened_queries, sub_select_queries);
        Py_DECREF(sub_select_queries);
      } else {
        Py_DECREF(flattened_queries);
        throw HogQLParsingError("Unexpected query node type: " + string(Py_TYPE(query)->tp_name));
      }
    }
    return build_ast_node("SelectUnionQuery", "{s:N}", "select_queries", flattened_queries);
  }

  VISIT(SelectStmtWithParens) {
    auto select_stmt_ctx = ctx->selectStmt();
    if (select_stmt_ctx) {
      return visit(select_stmt_ctx);
    }
    return visit(ctx->selectUnionStmt());
  }

  VISIT(SelectStmt) {
    PyObject* select_query = build_ast_node(
        "SelectQuery", "{s:N,s:N,s:N,s:N,s:N,s:N,s:N,s:N,s:N}", "ctes", visitAsPyObjectOrNone(ctx->withClause()),
        "select", visitAsPyObjectOrEmptyList(ctx->columnExprList()), "distinct",
        Py_NewRef(ctx->DISTINCT() ? Py_True : Py_False), "select_from", visitAsPyObjectOrNone(ctx->fromClause()),
        "where", visitAsPyObjectOrNone(ctx->whereClause()), "prewhere", visitAsPyObjectOrNone(ctx->prewhereClause()),
        "having", visitAsPyObjectOrNone(ctx->havingClause()), "group_by", visitAsPyObjectOrNone(ctx->groupByClause()),
        "order_by", visitAsPyObjectOrNone(ctx->orderByClause())
    );

    auto window_clause_ctx = ctx->windowClause();
    if (window_clause_ctx) {
      auto window_expr_ctxs = window_clause_ctx->windowExpr();
      auto identifier_ctxs = window_clause_ctx->identifier();
      PyObject* window_exprs = PyDict_New();
      PyObject_SetAttrString(select_query, "window_exprs", window_exprs);
      for (size_t i = 0; i < window_expr_ctxs.size(); i++) {
        PyDict_SetItemString(
            window_exprs, visitAsString(identifier_ctxs[i]).c_str(), visitAsPyObject(window_expr_ctxs[i])
        );
      }
    }

    auto limit_and_offset_clause_ctx = ctx->limitAndOffsetClause();
    if (limit_and_offset_clause_ctx) {
      PyObject_SetAttrString(select_query, "limit", visitAsPyObject(limit_and_offset_clause_ctx->columnExpr(0)));
      auto offset_ctx = limit_and_offset_clause_ctx->columnExpr(1);
      if (offset_ctx) {
        PyObject_SetAttrString(select_query, "offset", visitAsPyObject(offset_ctx));
      }
      auto limit_by_exprs_ctx = limit_and_offset_clause_ctx->columnExprList();
      if (limit_by_exprs_ctx) {
        PyObject_SetAttrString(select_query, "limit_by", visitAsPyObject(limit_by_exprs_ctx));
      }
      if (limit_and_offset_clause_ctx->WITH() && limit_and_offset_clause_ctx->TIES()) {
        PyObject_SetAttrString(select_query, "limit_with_ties", Py_NewRef(Py_True));
      }
    } else {
      auto offset_only_clause_ctx = ctx->offsetOnlyClause();
      if (offset_only_clause_ctx) {
        PyObject_SetAttrString(select_query, "offset", visitAsPyObject(offset_only_clause_ctx->columnExpr()));
      }
    }

    auto array_join_clause_ctx = ctx->arrayJoinClause();
    if (array_join_clause_ctx) {
      if (Py_IsNone(PyObject_GetAttrString(select_query, "select_from"))) {
        Py_DECREF(select_query);
        throw HogQLSyntaxError("Using ARRAY JOIN without a FROM clause is not permitted");
      }
      PyObject_SetAttrString(
          select_query, "array_join_op",
          PyUnicode_FromString(
              array_join_clause_ctx->LEFT()    ? "LEFT ARRAY JOIN"
              : array_join_clause_ctx->INNER() ? "INNER ARRAY JOIN"
                                               : "ARRAY JOIN"
          )
      );

      PyObject* array_join_list = visitAsPyObject(array_join_clause_ctx->columnExprList());
      for (size_t i = 0; i < PyList_Size(array_join_list); i++) {
        PyObject* expr = PyList_GET_ITEM(array_join_list, i);
        if (!is_ast_node_instance(expr, "Alias")) {
          Py_DECREF(array_join_list);
          Py_DECREF(select_query);
          throw HogQLSyntaxError("ARRAY JOIN must be used with an alias");
        }
      }
      PyObject_SetAttrString(select_query, "array_join_list", array_join_list);
    }

    if (ctx->topClause()) {
      throw HogQLNotImplementedError("Unsupported: SelectStmt.topClause()");
    }
    if (ctx->settingsClause()) {
      throw HogQLNotImplementedError("Unsupported: SelectStmt.settingsClause()");
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

  VISIT(JoinExprOp) {
    PyObject* join1 = visitAsPyObject(ctx->joinExpr(0));
    PyObject* join2 = visitAsPyObject(ctx->joinExpr(1));

    auto join_op_ctx = ctx->joinOp();
    if (join_op_ctx) {
      string join_op = visitAsString(join_op_ctx);
      join_op.append(" JOIN");
      PyObject_SetAttrString(join1, "join_type", PyUnicode_FromStringAndSize(join_op.c_str(), join_op.size()));
    } else {
      PyObject_SetAttrString(join1, "join_type", PyUnicode_FromString("JOIN"));
    }
    PyObject_SetAttrString(join2, "constraint", visitAsPyObject(ctx->joinConstraintClause()));

    PyObject* last_join = join1;
    PyObject* next_join = PyObject_GetAttrString(last_join, "next_join");
    while (!Py_IsNone(next_join)) {
      last_join = next_join;
      next_join = PyObject_GetAttrString(last_join, "next_join");
    }
    PyObject_SetAttrString(last_join, "next_join", join2);

    return join1;
  }

  VISIT(JoinExprTable) {
    PyObject* sample = visitAsPyObjectOrNone(ctx->sampleClause());
    PyObject* table = visitAsPyObject(ctx->tableExpr());
    PyObject* table_final = Py_NewRef(ctx->FINAL() ? Py_True : Py_None);
    if (is_ast_node_instance(table, "JoinExpr")) {
      // visitTableExprAlias returns a JoinExpr to pass the alias
      // visitTableExprFunction returns a JoinExpr to pass the args
      PyObject_SetAttrString(table, "table_final", table_final);
      PyObject_SetAttrString(table, "sample", sample);
      return table;
    }
    return build_ast_node("JoinExpr", "{s:N,s:N,s:N}", "table", table, "table_final", table_final, "sample", sample);
  }

  VISIT(JoinExprParens) { return visit(ctx->joinExpr()); }

  VISIT(JoinExprCrossOp) {
    PyObject* join1 = visitAsPyObject(ctx->joinExpr(0));
    PyObject* join2 = visitAsPyObject(ctx->joinExpr(1));
    PyObject_SetAttrString(join1, "join_type", PyUnicode_FromString("CROSS JOIN"));

    PyObject* last_join = join1;
    PyObject* next_join = PyObject_GetAttrString(last_join, "next_join");
    while (!Py_IsNone(next_join)) {
      last_join = next_join;
      next_join = PyObject_GetAttrString(last_join, "next_join");
    }
    PyObject_SetAttrString(last_join, "next_join", join2);

    return join1;
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
    if (ctx->USING()) {
      throw HogQLNotImplementedError("Unsupported: JOIN ... USING");
    }
    PyObject* column_expr_list = visitAsPyObject(ctx->columnExprList());
    if (PyList_Size(column_expr_list) != 1) {
      Py_DECREF(column_expr_list);
      throw HogQLNotImplementedError("Unsupported: JOIN ... ON with multiple expressions");
    }
    return build_ast_node("JoinConstraint", "{s:N}", "expr", PyList_GET_ITEM(column_expr_list, 0));
  }

  VISIT(SampleClause) {
    PyObject* sample_ratio_expr = visitAsPyObject(ctx->ratioExpr(0));
    PyObject* offset_ratio_expr = ctx->OFFSET() ? visitAsPyObjectOrNone(ctx->ratioExpr(1)) : Py_NewRef(Py_None);
    return build_ast_node(
        "SampleExpr", "{s:N,s:N}", "sample_value", sample_ratio_expr, "offset_value", offset_ratio_expr
    );
  }

  VISIT(OrderExprList) { return visitPyListOfObjects(ctx->orderExpr()); }

  VISIT(OrderExpr) {
    const char* order = ctx->DESC() || ctx->DESCENDING() ? "DESC" : "ASC";
    return build_ast_node("OrderExpr", "{s:N,s:s}", "expr", visitAsPyObject(ctx->columnExpr()), "order", order);
  }

  VISIT(RatioExpr) {
    auto number_literal_ctxs = ctx->numberLiteral();

    auto left_ctx = number_literal_ctxs[0];
    auto right_ctx = ctx->SLASH() && number_literal_ctxs.size() > 1 ? number_literal_ctxs[1] : NULL;

    return build_ast_node(
        "RatioExpr", "{s:N,s:N}", "left", visitAsPyObject(left_ctx), "right", visitAsPyObjectOrNone(right_ctx)
    );
  }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  VISIT(WindowExpr) {
    auto frame_ctx = ctx->winFrameClause();
    PyObject* frame = visitAsPyObjectOrNone(frame_ctx);
    PyObject* partition_by = visitAsPyObjectOrNone(ctx->winPartitionByClause());
    PyObject* order_by = visitAsPyObjectOrNone(ctx->winOrderByClause());
    PyObject* frame_method = frame_ctx && frame_ctx->RANGE()  ? PyUnicode_FromString("RANGE")
                             : frame_ctx && frame_ctx->ROWS() ? PyUnicode_FromString("ROWS")
                                                              : Py_NewRef(Py_None);
    PyObject* frame_start = PyTuple_Check(frame) ? PyTuple_GetItem(frame, 0) : frame;
    PyObject* frame_end = PyTuple_Check(frame) ? PyTuple_GetItem(frame, 1) : Py_NewRef(Py_None);
    return build_ast_node(
        "WindowExpr", "{s:N,s:N,s:N,s:N,s:N}", "partition_by", partition_by, "order_by", order_by, "frame_method",
        frame_method, "frame_start", frame_start, "frame_end", frame_end
    );
  }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  VISIT(FrameBetween) {
    return Py_BuildValue("OO", visitAsPyObject(ctx->winFrameBound(0)), visitAsPyObject(ctx->winFrameBound(1)));
  }

  VISIT(WinFrameBound) {
    if (ctx->PRECEDING() || ctx->FOLLOWING()) {
      PyObject* number;
      if (ctx->numberLiteral()) {
        number = PyObject_GetAttrString(visitAsPyObject(ctx->numberLiteral()), "value");
      } else {
        number = Py_NewRef(Py_None);
      }
      return build_ast_node(
          "WindowFrameExpr", "{s:s,s:N}", "frame_type", ctx->PRECEDING() ? "PRECEDING" : "FOLLOWING", "frame_value",
          number
      );
    } else {
      return build_ast_node("WindowFrameExpr", "{s:s}", "frame_type", "CURRENT ROW");
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
    return build_ast_node(
        "Call", "{s:s, s:[O,O,O]}", "name", "if", "args", visitAsPyObject(ctx->columnExpr(0)),
        visitAsPyObject(ctx->columnExpr(1)), visitAsPyObject(ctx->columnExpr(2))
    );
  }

  VISIT(ColumnExprAlias) {
    string alias;
    if (ctx->alias()) {
      alias = visitAsString(ctx->alias());
    } else if (ctx->identifier()) {
      alias = visitAsString(ctx->identifier());
    } else if (ctx->STRING_LITERAL()) {
      alias = parse_string_literal(ctx->STRING_LITERAL());
    } else {
      throw HogQLParsingError("A ColumnExprAlias must have the alias in some form");
    }
    PyObject* expr = visitAsPyObject(ctx->columnExpr());

    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), alias) != RESERVED_KEYWORDS.end()) {
      Py_DECREF(expr);
      throw HogQLSyntaxError("Alias is a reserved keyword");
    }

    return build_ast_node("Alias", "{s:N,s:s#}", "expr", expr, "alias", alias.c_str(), alias.size());
  }

  VISIT_UNSUPPORTED(ColumnExprExtract)

  VISIT(ColumnExprNegate) {
    return build_ast_node(
        "ArithmeticOperation", "{s:N,s:N,s:N}", "left", build_ast_node("Constant", "{s:i}", "value", 0), "right",
        visitAsPyObject(ctx->columnExpr()), "op", get_ast_enum_member("ArithmeticOperationOp", "Sub")
    );
  }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectUnionStmt()); }

  VISIT(ColumnExprArray) {
    auto column_expr_list_ctx = ctx->columnExprList();
    PyObject* exprs = visitAsPyObjectOrEmptyList(column_expr_list_ctx);
    return build_ast_node("Array", "{s:N}", "exprs", exprs);
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
      throw HogQLParsingError("Unsupported value of rule ColumnExprPrecedence1");
    }
    PyObject* left = visitAsPyObject(ctx->left);
    PyObject* right = visitAsPyObject(ctx->right);
    return build_ast_node("ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
  }

  VISIT(ColumnExprPrecedence2) {
    PyObject* left = visitAsPyObject(ctx->left);
    PyObject* right = visitAsPyObject(ctx->right);

    if (ctx->PLUS()) {
      return build_ast_node(
          "ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op",
          get_ast_enum_member("ArithmeticOperationOp", "Add")
      );
    } else if (ctx->DASH()) {
      return build_ast_node(
          "ArithmeticOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op",
          get_ast_enum_member("ArithmeticOperationOp", "Sub")
      );
    } else if (ctx->CONCAT()) {
      PyObject* args;
      if (is_ast_node_instance(left, "Call") &&
          PyObject_RichCompareBool(PyObject_GetAttrString(left, "name"), PyUnicode_FromString("concat"), Py_EQ)) {
        args = PyObject_GetAttrString(left, "args");
      } else {
        args = PyList_New(1);
        PyList_SET_ITEM(args, 0, left);
        Py_INCREF(left);  // PyList_SET_ITEM doesn't increment refcount, as opposed to PyList_Append
      }

      if (is_ast_node_instance(right, "Call") &&
          PyObject_RichCompareBool(PyObject_GetAttrString(right, "name"), PyUnicode_FromString("concat"), Py_EQ)) {
        PyObject* right_args = PyObject_GetAttrString(right, "args");
        X_PyList_Extend(args, right_args);
        Py_DECREF(right_args);
      } else {
        PyList_Append(args, right);
      }
      Py_DECREF(right);
      Py_DECREF(left);
      return build_ast_node("Call", "{s:s,s:N}", "name", "concat", "args", args);
    } else {
      Py_DECREF(right);
      Py_DECREF(left);
      throw HogQLParsingError("Unsupported value of rule ColumnExprPrecedence2");
      return NULL;
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
      throw HogQLParsingError("Unsupported value of rule ColumnExprPrecedence3");
    }

    PyObject* left = visitAsPyObject(ctx->left);
    PyObject* right = visitAsPyObject(ctx->right);

    return build_ast_node("CompareOperation", "{s:N,s:N,s:N}", "left", left, "right", right, "op", op);
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
      throw HogQLParsingError("Unsupported value of rule ColumnExprInterval");
    }

    PyObject* arg = visitAsPyObject(ctx->columnExpr());
    return build_ast_node("Call", "{s:s,s:[N]}", "name", name, "args", arg);
  }

  VISIT(ColumnExprIsNull) {
    return build_ast_node(
        "CompareOperation", "{s:N,s:N,s:N}", "left", visitAsPyObject(ctx->columnExpr()), "right",
        build_ast_node("Constant", "{s:O}", "value", Py_None), "op",
        get_ast_enum_member("CompareOperationOp", ctx->NOT() ? "NotEq" : "Eq")

    );
  }

  VISIT_UNSUPPORTED(ColumnExprTrim)

  VISIT(ColumnExprTuple) {
    auto column_expr_list_ctx = ctx->columnExprList();
    return build_ast_node("Tuple", "{s:N}", "exprs", visitAsPyObjectOrEmptyList(column_expr_list_ctx));
  }

  VISIT(ColumnExprArrayAccess) {
    PyObject* object = visitAsPyObject(ctx->columnExpr(0));
    PyObject* property = visitAsPyObject(ctx->columnExpr(1));
    if (is_ast_node_instance(property, "Constant") &&
        PyObject_RichCompareBool(PyObject_GetAttrString(property, "value"), PyLong_FromLong(0), Py_EQ)) {
      Py_DECREF(property);
      Py_DECREF(object);
      throw HogQLSyntaxError("SQL indexes start from one, not from zero. E.g: array[1]");
    }
    return build_ast_node("ArrayAccess", "{s:N,s:N}", "array", object, "property", property);
  }

  VISIT(ColumnExprPropertyAccess) {
    PyObject* object = visitAsPyObject(ctx->columnExpr());
    string identifier = visitAsString(ctx->identifier());
    PyObject* property = build_ast_node("Constant", "{s:s#}", "value", identifier.c_str(), identifier.size());
    return build_ast_node("ArrayAccess", "{s:N,s:N}", "array", object, "property", property);
  }

  VISIT_UNSUPPORTED(ColumnExprBetween)

  VISIT(ColumnExprParens) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnExprTimestamp)

  VISIT(ColumnExprAnd) {
    PyObject* left = visitAsPyObject(ctx->columnExpr(0));
    PyObject* right = visitAsPyObject(ctx->columnExpr(1));
    PyObject* exprs;
    if (is_ast_node_instance(left, "And")) {
      exprs = PyObject_GetAttrString(left, "exprs");
    } else {
      exprs = PyList_New(1);
      PyList_SET_ITEM(exprs, 0, left);
      Py_INCREF(left);
    }
    if (is_ast_node_instance(right, "And")) {
      PyObject* right_exprs = PyObject_GetAttrString(right, "exprs");
      X_PyList_Extend(exprs, right_exprs);
      Py_DECREF(right_exprs);
    } else {
      PyList_Append(exprs, right);
    }

    return build_ast_node("And", "{s:N}", "exprs", exprs);
  }

  VISIT(ColumnExprOr) {
    PyObject* left = visitAsPyObject(ctx->columnExpr(0));
    PyObject* right = visitAsPyObject(ctx->columnExpr(1));
    PyObject* exprs;
    if (is_ast_node_instance(left, "Or")) {
      exprs = PyObject_GetAttrString(left, "exprs");
    } else {
      exprs = PyList_New(1);
      PyList_SET_ITEM(exprs, 0, left);
      Py_INCREF(left);
    }
    if (is_ast_node_instance(right, "Or")) {
      PyObject* right_exprs = PyObject_GetAttrString(right, "exprs");
      X_PyList_Extend(exprs, right_exprs);
      Py_DECREF(right_exprs);
    } else {
      PyList_Append(exprs, right);
    }

    return build_ast_node("Or", "{s:N}", "exprs", exprs);
  }

  VISIT(ColumnExprTupleAccess) {
    PyObject* tuple = visitAsPyObject(ctx->columnExpr());
    int index = stoi(ctx->DECIMAL_LITERAL()->getText());
    if (index == 0) {
      Py_DECREF(tuple);
      throw HogQLSyntaxError("SQL indexes start from one, not from zero. E.g: array[1]");
    }
    return build_ast_node("TupleAccess", "{s:N,s:i}", "tuple", tuple, "index", index);
  }

  VISIT(ColumnExprCase) {
    auto column_expr_ctx = ctx->columnExpr();
    size_t columns_size = column_expr_ctx.size();
    PyObject* columns = visitPyListOfObjects(column_expr_ctx);
    if (ctx->caseExpr) {
      PyObject* args = PyList_New(4);
      PyObject* arg_0 = Py_NewRef(PyList_GetItem(columns, 0));
      PyObject* arg_1 = build_ast_node("Array", "{s:[]}", "exprs");
      PyObject* arg_2 = build_ast_node("Array", "{s:[]}", "exprs");
      PyObject* arg_3 = Py_NewRef(PyList_GetItem(columns, columns_size - 1));
      PyList_SET_ITEM(args, 0, arg_0);
      PyList_SET_ITEM(args, 1, arg_1);
      PyList_SET_ITEM(args, 2, arg_2);
      PyList_SET_ITEM(args, 3, arg_3);
      PyObject* expr_lists[2] = {PyObject_GetAttrString(arg_1, "exprs"), PyObject_GetAttrString(arg_2, "exprs")};
      for (size_t index = 0; index < columns_size - 2; index++) {
        PyList_Append(expr_lists[index % 2], PyList_GetItem(columns, index));
      }
      Py_DECREF(expr_lists[0]);
      Py_DECREF(expr_lists[1]);
      Py_DECREF(columns);
      return build_ast_node("Call", "{s:s,s:N}", "name", "transform", "args", args);
    } else {
      return build_ast_node("Call", "{s:s,s:N}", "name", columns_size == 3 ? "if" : "multiIf", "args", columns);
    }
  }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) { return build_ast_node("Not", "{s:N}", "expr", visitAsPyObject(ctx->columnExpr())); }

  VISIT(ColumnExprWinFunctionTarget) {
    auto column_expr_list_ctx = ctx->columnExprList();
    string name = visitAsString(ctx->identifier(0));
    string over_identifier = visitAsString(ctx->identifier(1));
    PyObject* args = visitAsPyObjectOrEmptyList(column_expr_list_ctx);
    return build_ast_node(
        "WindowFunction", "{s:s#,s:N,s:s#}", "name", name.c_str(), name.size(), "args", args, "over_identifier",
        over_identifier.c_str(), over_identifier.size()

    );
  }

  VISIT(ColumnExprWinFunction) {
    string identifier = visitAsString(ctx->identifier());
    auto column_expr_list_ctx = ctx->columnExprList();
    PyObject* args = visitAsPyObjectOrEmptyList(column_expr_list_ctx);
    PyObject* over_expr = visitAsPyObjectOrNone(ctx->windowExpr());
    return build_ast_node(
        "WindowFunction", "{s:s#,s:N,s:N}", "name", identifier.c_str(), identifier.size(), "args", args, "over_expr",
        over_expr
    );
  }

  VISIT(ColumnExprIdentifier) { return visit(ctx->columnIdentifier()); }

  VISIT(ColumnExprFunction) {
    string name = visitAsString(ctx->identifier());
    PyObject* parameters = visitAsPyObjectOrNone(ctx->columnExprList());
    auto column_arg_list_ctx = ctx->columnArgList();
    PyObject* args = visitAsPyObjectOrEmptyList(column_arg_list_ctx);
    PyObject* distinct = ctx->DISTINCT() ? Py_True : Py_False;
    return build_ast_node(
        "Call", "{s:s#,s:N,s:N,s:O}", "name", name.c_str(), name.size(), "params", parameters, "args", args, "distinct",
        distinct
    );
  }

  VISIT(ColumnExprAsterisk) {
    auto table_identifier_ctx = ctx->tableIdentifier();
    if (table_identifier_ctx) {
      vector<string> table = any_cast<vector<string>>(visit(table_identifier_ctx));
      table.push_back("*");
      return build_ast_node("Field", "{s:N}", "chain", vector_to_list_string(table));
    }
    return build_ast_node("Field", "{s:[s]}", "chain", "*");
  }

  VISIT(ColumnArgList) { return visitPyListOfObjects(ctx->columnArgExpr()); }

  VISIT(ColumnLambdaExpr) {
    PyObject* args = visitPyListOfObjects(ctx->identifier());
    return build_ast_node("Lambda", "{s:N,s:N}", "args", args, "expr", visitAsPyObject(ctx->columnExpr()));
  }

  VISIT(WithExprList) {
    PyObject* ctes = PyDict_New();
    for (auto with_expr_ctx : ctx->withExpr()) {
      PyObject* cte = visitAsPyObject(with_expr_ctx);
      PyObject* name = PyObject_GetAttrString(cte, "name");
      PyDict_SetItem(ctes, name, cte);
      Py_DECREF(cte);
    }
    return ctes;
  }

  VISIT(WithExprSubquery) {
    PyObject* subquery = visitAsPyObject(ctx->selectUnionStmt());
    string name = visitAsString(ctx->identifier());
    return build_ast_node(
        "CTE", "{s:s#,s:N,s:s}", "name", name.c_str(), name.size(), "expr", subquery, "cte_type", "subquery"
    );
  }

  VISIT(WithExprColumn) {
    PyObject* expr = visitAsPyObject(ctx->columnExpr());
    string name = visitAsString(ctx->identifier());
    return build_ast_node(
        "CTE", "{s:s#,s:N,s:s}", "name", name.c_str(), name.size(), "expr", expr, "cte_type", "column"
    );
  }

  VISIT(ColumnIdentifier) {
    auto placeholder_ctx = ctx->PLACEHOLDER();
    if (placeholder_ctx) {
      string placeholder = parse_string_literal(placeholder_ctx);
      return build_ast_node("Placeholder", "{s:s#}", "field", placeholder.c_str(), placeholder.size());
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
        return build_ast_node("Constant", "{s:O}", "value", Py_True);
      }
      if (!text.compare("false")) {
        return build_ast_node("Constant", "{s:O}", "value", Py_False);
      }
      return build_ast_node("Field", "{s:N}", "chain", vector_to_list_string(nested));
    }
    vector<string> table_plus_nested = table;
    table_plus_nested.insert(table_plus_nested.end(), nested.begin(), nested.end());
    return build_ast_node("Field", "{s:N}", "chain", vector_to_list_string(table_plus_nested));
  }

  VISIT(NestedIdentifier) {
    vector<string> result;
    for (auto identifier_ctx : ctx->identifier()) {
      result.push_back(visitAsString(identifier_ctx));
    }
    return result;
  }

  VISIT(TableExprIdentifier) {
    vector<string> chain = any_cast<vector<string>>(visit(ctx->tableIdentifier()));
    return build_ast_node("Field", "{s:N}", "chain", vector_to_list_string(chain));
  }

  VISIT(TableExprSubquery) { return visit(ctx->selectUnionStmt()); }

  VISIT(TableExprPlaceholder) {
    string placeholder = parse_string_literal(ctx->PLACEHOLDER());
    return build_ast_node("Placeholder", "{s:s#}", "field", placeholder.c_str(), placeholder.size());
  }

  VISIT(TableExprAlias) {
    auto alias_ctx = ctx->alias();
    string alias = any_cast<string>(alias_ctx ? visit(alias_ctx) : visit(ctx->identifier()));
    if (find(RESERVED_KEYWORDS.begin(), RESERVED_KEYWORDS.end(), alias) != RESERVED_KEYWORDS.end()) {
      throw HogQLSyntaxError("Alias is a reserved keyword");
    }
    PyObject* table = visitAsPyObject(ctx->tableExpr());
    PyObject* py_alias = PyUnicode_FromStringAndSize(alias.c_str(), alias.size());
    if (is_ast_node_instance(table, "JoinExpr")) {
      PyObject_SetAttrString(table, "alias", py_alias);
      return table;
    }
    return build_ast_node("JoinExpr", "{s:N,s:N}", "table", table, "alias", py_alias);
  }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  VISIT(TableFunctionExpr) {
    string name = visitAsString(ctx->identifier());
    PyObject* table_args;
    auto table_args_ctx = ctx->tableArgList();
    if (table_args_ctx) {
      table_args = visitAsPyObject(table_args_ctx);
    } else {
      table_args = Py_NewRef(Py_None);
    }
    return build_ast_node(
        "JoinExpr", "{s:N,s:N}", "table", build_ast_node("Field", "{s:N}", "chain", vector_to_list_string({name})),
        "table_args", table_args
    );
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
    PyObject* value;
    PyObject* result;
    if (text.find(".") != string::npos || text.find("e") != string::npos || !text.compare("-inf") ||
        !text.compare("inf") || !text.compare("nan")) {
      PyObject* pyText = PyUnicode_FromStringAndSize(text.c_str(), text.size());
      value = PyFloat_FromString(pyText);
      result = build_ast_node("Constant", "{s:N}", "value", value);
      Py_DECREF(pyText);
    } else {
      value = PyLong_FromString(text.c_str(), NULL, 10);
      result = build_ast_node("Constant", "{s:N}", "value", value);
    }

    return result;
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      return build_ast_node("Constant", "{s:O}", "value", Py_None);
    }
    auto string_literal_terminal = ctx->STRING_LITERAL();
    if (string_literal_terminal) {
      string text = parse_string_literal(string_literal_terminal);
      return build_ast_node("Constant", "{s:s#}", "value", text.c_str(), text.size());
    }
    return visitChildren(ctx);
  }

  VISIT_UNSUPPORTED(Interval)

  VISIT_UNSUPPORTED(Keyword)

  VISIT_UNSUPPORTED(KeywordForAlias)

  VISIT(Alias) {
    string text = ctx->getText();
    if (text.size() >= 2) {
      char first = text[0];
      char last = text[text.size() - 1];
      if ((first == '`' && last == '`') || (first == '"' && last == '"')) {
        return parse_string(text);  // Quotes matching already guaranteed, so not catching error
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
        return parse_string(text);  // Quotes matching already guaranteed, so not catching error
      }
    }
    return text;
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    return build_ast_node(
        "Call", "{s:s, s:[O,O]}", "name", "ifNull", "args", visitAsPyObject(ctx->columnExpr(0)),
        visitAsPyObject(ctx->columnExpr(1))
    );
  }
};

HogQLParser get_parser(const char* statement) {
  auto input_stream = new antlr4::ANTLRInputStream(statement, strnlen(statement, 65536));
  auto lexer = new HogQLLexer(input_stream);
  auto stream = new antlr4::CommonTokenStream(lexer);
  return HogQLParser(stream);
}

// MODULE STATE

parser_state* get_module_state(PyObject* module) {
  return static_cast<parser_state*>(PyModule_GetState(module));
}

// MODULE METHODS

static PyObject* parse_expr(PyObject* self, PyObject* args, PyObject* kwargs) {
  const char* str;
  int start;  // TODO: Use start

  static char* kwlist[] = {"expr", "start", NULL};

  // s = str, | = optionals start here, i = int
  if (!PyArg_ParseTupleAndKeywords(args, kwargs, "s|i", kwlist, &str, &start)) {
    return NULL;
  }
  HogQLParser parser = get_parser(str);
  HogQLParser::ExprContext* parse_tree = parser.expr();
  HogQLParseTreeConverter converter = HogQLParseTreeConverter(get_module_state(self));
  return converter.visitAsPyObjectFinal(parse_tree);
}

static PyObject* parse_order_expr(PyObject* self, PyObject* args) {
  const char* str;
  if (!PyArg_ParseTuple(args, "s", &str)) {
    return NULL;
  }
  HogQLParser parser = get_parser(str);
  HogQLParser::OrderExprContext* parse_tree = parser.orderExpr();
  HogQLParseTreeConverter converter = HogQLParseTreeConverter(get_module_state(self));
  return converter.visitAsPyObjectFinal(parse_tree);
}

static PyObject* parse_select(PyObject* self, PyObject* args) {
  const char* str;
  if (!PyArg_ParseTuple(args, "s", &str)) {
    return NULL;
  }
  HogQLParser parser = get_parser(str);
  HogQLParser::SelectContext* parse_tree = parser.select();
  HogQLParseTreeConverter converter = HogQLParseTreeConverter(get_module_state(self));
  return converter.visitAsPyObjectFinal(parse_tree);
}

// MODULE SETUP

static PyMethodDef parser_methods[] = {
    {.ml_name = "parse_expr",
     // The cast of the function is necessary since PyCFunction values only take two
     // PyObject* parameters, and parse_expr() takes three.
     .ml_meth = (PyCFunction)(void (*)(void))parse_expr,
     .ml_flags = METH_VARARGS | METH_KEYWORDS,
     .ml_doc = "Parse the HogQL expression string into an AST"},
    {.ml_name = "parse_order_expr",
     .ml_meth = parse_order_expr,
     .ml_flags = METH_VARARGS,
     .ml_doc = "Parse the ORDER BY clause string into an AST"},
    {.ml_name = "parse_select",
     .ml_meth = parse_select,
     .ml_flags = METH_VARARGS,
     .ml_doc = "Parse the HogQL SELECT statement string into an AST"},
    {NULL, NULL, 0, NULL}};

static int parser_modexec(PyObject* module) {
  parser_state* state = get_module_state(module);
  state->ast_module = PyImport_ImportModule("posthog.hogql.ast");
  if (!state->ast_module) {
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
    {0, NULL}};

static int parser_traverse(PyObject* module, visitproc visit, void* arg) {
  parser_state* state = get_module_state(module);
  Py_VISIT(state->ast_module);
  return 0;
}

static int parser_clear(PyObject* module) {
  parser_state* state = get_module_state(module);
  Py_CLEAR(state->ast_module);
  return 0;
}

static struct PyModuleDef parser = {
    PyModuleDef_HEAD_INIT,       .m_name = "parser",      .m_doc = "HogQL parsing",      .m_size = sizeof(parser_state),
    .m_methods = parser_methods, .m_slots = parser_slots, .m_traverse = parser_traverse, .m_clear = parser_clear,
};

PyMODINIT_FUNC PyInit_hogql_parser(void) {
  return PyModuleDef_Init(&parser);
}
