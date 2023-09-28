#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <boost/algorithm/string.hpp>
#include <format>
#include <string>

#include "HogQLLexer.h"
#include "HogQLParser.h"
#include "HogQLParserBaseVisitor.h"

#include "string.h"

#define VISIT(RULE) virtual any visit##RULE(HogQLParser::RULE##Context* ctx) override
#define VISIT_UNSUPPORTED(RULE)                                             \
  VISIT(RULE) {                                                             \
    PyErr_SetString(PyExc_NotImplementedError, "Unsupported rule: " #RULE); \
    return NULL;                                                            \
  }
#define GET_STATE(MODULE) static_cast<parser_state*>(PyModule_GetState(MODULE))

using namespace std;

// MODULE STATE

typedef struct {
  PyObject* ast_module;
} parser_state;

// PARSING AND AST CONVERSION

/// Builds an AST node of the specified type. Decrements the refcount for kwargs. Return value: New reference.
PyObject* build_ast_node(parser_state* state, const char* type_name, PyObject* kwargs) {
  // Check that kwargs are a dict
  if (!kwargs) {
    PyErr_SetString(PyExc_RuntimeError, "build_ast_node kwargs cannot be NULL");
    return NULL;
  }
  if (!PyDict_Check(kwargs)) {
    Py_DECREF(kwargs);
    PyErr_SetString(PyExc_RuntimeError, "build_ast_node kwargs must be a dict");
    return NULL;
  }
  PyObject* node_type = PyObject_GetAttrString(state->ast_module, type_name);
  PyObject* args = PyTuple_New(0);
  PyObject* result = PyObject_Call(node_type, args, kwargs);
  Py_DECREF(kwargs);
  Py_DECREF(args);
  Py_DECREF(node_type);
  return result;
}

PyObject* get_ast_enum_val(parser_state* state, const char* enum_name, const char* enum_val) {
  PyObject* enum_type = PyObject_GetAttrString(state->ast_module, enum_name);
  PyObject* result = PyObject_GetAttrString(enum_type, enum_val);
  Py_DECREF(enum_type);
  return result;
}

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

 public:
  HogQLParseTreeConverter(parser_state* state) : state(state) {}

  VISIT(Select) {
    auto selectUnionStmt = ctx->selectUnionStmt();
    if (selectUnionStmt) {
      return visit(selectUnionStmt);
    }
    return visit(ctx->selectStmt());
  }

  // VISIT(SelectUnionStmt) {
  //     select_queries: List[ast.SelectQuery | ast.SelectUnionQuery] = [
  //         visit(select) for select in ctx->selectStmtWithParens()
  //     ]
  //     flattened_queries: List[ast.SelectQuery] = []
  //     for query in select_queries:
  //         if (isinstance(query, ast.SelectQuery)) {
  //             flattened_queries.append(query)
  //         } else if (isinstance(query, ast.SelectUnionQuery)) {
  //             flattened_queries.extend(query.select_queries)
  //         } else {
  //             raise Exception(f"Unexpected query node type {type(query).__name__}")
  //     if (len(flattened_queries) == 1) {
  //         return flattened_queries[0]
  //     return ast.SelectUnionQuery(select_queries=flattened_queries)

  VISIT(SelectUnionStmt) {
    vector<PyObject*> select_queries;
    for (auto select : ctx->selectStmtWithParens()) {
      select_queries.push_back(any_cast<PyObject*>(visit(select)));
    }
  }

  VISIT(SelectStmtWithParens) {
    auto selectStmt = ctx->selectStmt();
    if (selectStmt) {
      return visit(selectStmt);
    }
    return visit(ctx->selectUnionStmt());
  }

  // VISIT(SelectStmt) {
  //     select_query = ast.SelectQuery(
  //         ctes=visit(ctx->withClause()) if ctx->withClause() else None,
  //         select=visit(ctx->columnExprList()) if ctx->columnExprList() else [],
  //         distinct=True if ctx->DISTINCT() else None,
  //         select_from=visit(ctx->fromClause()) if ctx->fromClause() else None,
  //         where=visit(ctx->whereClause()) if ctx->whereClause() else None,
  //         prewhere=visit(ctx->prewhereClause()) if ctx->prewhereClause() else None,
  //         having=visit(ctx->havingClause()) if ctx->havingClause() else None,
  //         group_by=visit(ctx->groupByClause()) if ctx->groupByClause() else None,
  //         order_by=visit(ctx->orderByClause()) if ctx->orderByClause() else None,
  //     )

  //     if (window_clause := ctx->windowClause()) {
  //         select_query.window_exprs = {}
  //         for index, window_expr in enumerate(window_clause.windowExpr()):
  //             name = visit(window_clause.identifier()[index])
  //             select_query.window_exprs[name] = visit(window_expr)

  //     if (limit_and_offset_clause := ctx->limitAndOffsetClause()) {
  //         select_query.limit = visit(limit_and_offset_clause.columnExpr(0))
  //         if (offset := limit_and_offset_clause.columnExpr(1)) {
  //             select_query.offset = visit(offset)
  //         if (limit_by_exprs := limit_and_offset_clause.columnExprList()) {
  //             select_query.limit_by = visit(limit_by_exprs)
  //         if (limit_and_offset_clause.WITH() and limit_and_offset_clause.TIES()) {
  //             select_query.limit_with_ties = True
  //     } else if ((offset_only_clause ) {= ctx->offsetOnlyClause()) {
  //         select_query.offset = visit(offset_only_clause.columnExpr())

  //     if (ctx->arrayJoinClause()) {
  //         array_join_clause = ctx->arrayJoinClause()
  //         if (select_query.select_from is None) {
  //             raise HogQLException("Using ARRAY JOIN without a FROM clause is not permitted")
  //         if (array_join_clause.LEFT()) {
  //             select_query.array_join_op = "LEFT ARRAY JOIN"
  //         } else if (array_join_clause.INNER()) {
  //             select_query.array_join_op = "INNER ARRAY JOIN"
  //         } else {
  //             select_query.array_join_op = "ARRAY JOIN"
  //         select_query.array_join_list = visit(array_join_clause.columnExprList())
  //         for expr in select_query.array_join_list:
  //             if (not isinstance(expr, ast.Alias)) {
  //                 raise HogQLException("ARRAY JOIN arrays must have an alias", start=expr.start, end=expr.end)

  //     if (ctx->topClause()) {
  //         raise NotImplementedException(f"Unsupported: SelectStmt.topClause()")
  //     if (ctx->settingsClause()) {
  //         raise NotImplementedException(f"Unsupported: SelectStmt.settingsClause()")

  //     return select_query

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

  // VISIT(LimitAndOffsetClauseClause) {
  //     raise Exception(f"Parsed as part of SelectStmt, can't parse directly")

  VISIT_UNSUPPORTED(SettingsClause)

  // VISIT(JoinExprOp) {
  //     join1: ast.JoinExpr = visit(ctx->joinExpr(0))
  //     join2: ast.JoinExpr = visit(ctx->joinExpr(1))

  //     if (ctx->joinOp()) {
  //         join2.join_type = f"{visit(ctx->joinOp())} JOIN"
  //     } else {
  //         join2.join_type = "JOIN"
  //     join2.constraint = visit(ctx->joinConstraintClause())

  //     last_join = join1
  //     while last_join.next_join is not None:
  //         last_join = last_join.next_join
  //     last_join.next_join = join2

  //     return join1

  // VISIT(JoinExprTable) {
  //     sample = None
  //     if (ctx->sampleClause()) {
  //         sample = visit(ctx->sampleClause())
  //     table = visit(ctx->tableExpr())
  //     table_final = True if ctx->FINAL() else None
  //     if (isinstance(table, ast.JoinExpr)) {
  //         # visitTableExprAlias returns a JoinExpr to pass the alias
  //         # visitTableExprFunction returns a JoinExpr to pass the args
  //         table.table_final = table_final
  //         table.sample = sample
  //         return table
  //     return ast.JoinExpr(table=table, table_final=table_final, sample=sample)

  VISIT(JoinExprParens) { return visit(ctx->joinExpr()); }

  // VISIT(JoinExprCrossOp) {
  //     join1: ast.JoinExpr = visit(ctx->joinExpr(0))
  //     join2: ast.JoinExpr = visit(ctx->joinExpr(1))
  //     join2.join_type = "CROSS JOIN"
  //     last_join = join1
  //     while last_join.next_join is not None:
  //         last_join = last_join.next_join
  //     last_join.next_join = join2
  //     return join1
  // }

  // VISIT(JoinOpInner) {
  //     tokens = []
  //     if (ctx->ALL()) {
  //         tokens.append("ALL")
  //     if (ctx->ANY()) {
  //         tokens.append("ANY")
  //     if (ctx->ASOF()) {
  //         tokens.append("ASOF")
  //     tokens.append("INNER")
  //     return " ".join(tokens)
  // }

  // VISIT(JoinOpLeftRight) {
  //     tokens = []
  //     if (ctx->LEFT()) {
  //         tokens.append("LEFT")
  //     if (ctx->RIGHT()) {
  //         tokens.append("RIGHT")
  //     if (ctx->OUTER()) {
  //         tokens.append("OUTER")
  //     if (ctx->SEMI()) {
  //         tokens.append("SEMI")
  //     if (ctx->ALL()) {
  //         tokens.append("ALL")
  //     if (ctx->ANTI()) {
  //         tokens.append("ANTI")
  //     if (ctx->ANY()) {
  //         tokens.append("ANY")
  //     if (ctx->ASOF()) {
  //         tokens.append("ASOF")
  //     return " ".join(tokens)
  // }

  // VISIT(JoinOpFull) {
  //     tokens = []
  //     if (ctx->LEFT()) {
  //         tokens.append("FULL")
  //     if (ctx->OUTER()) {
  //         tokens.append("OUTER")
  //     if (ctx->ALL()) {
  //         tokens.append("ALL")
  //     if (ctx->ANY()) {
  //         tokens.append("ANY")
  //     return " ".join(tokens)
  // }

  VISIT_UNSUPPORTED(JoinOpCross)

  // VISIT(JoinConstraintClause) {
  //     if (ctx->USING()) {
  //         raise NotImplementedException(f"Unsupported: JOIN ... USING")
  //     column_expr_list = visit(ctx->columnExprList())
  //     if (len(column_expr_list) != 1) {
  //         raise NotImplementedException(f"Unsupported: JOIN ... ON with multiple expressions")
  //     return ast.JoinConstraint(expr=column_expr_list[0])
  // }

  // VISIT(SampleClause) {
  //     ratio_expressions = ctx->ratioExpr()

  //     sample_ratio_expr = visit(ratio_expressions[0])
  //     offset_ratio_expr = visit(ratio_expressions[1]) if len(ratio_expressions) > 1 and ctx->OFFSET() else None

  //     return ast.SampleExpr(sample_value=sample_ratio_expr, offset_value=offset_ratio_expr)
  // }

  // VISIT(OrderExprList) {
  //     return [visit(expr) for expr in ctx->orderExpr()]
  // }

  // VISIT(OrderExpr) {
  //     order = "DESC" if ctx->DESC() or ctx->DESCENDING() else "ASC"
  //     return ast.OrderExpr(expr=visit(ctx->columnExpr()), order=cast(Literal["ASC", "DESC"], order))
  // }

  // VISIT(RatioExpr) {
  //     number_literals = ctx->numberLiteral()

  //     left = number_literals[0]
  //     right = number_literals[1] if ctx->SLASH() and len(number_literals) > 1 else None

  //     return ast.RatioExpr(
  //         left=visitNumberLiteral(left), right=visitNumberLiteral(right) if right else None
  //     )
  // }

  VISIT_UNSUPPORTED(SettingExprList)

  VISIT_UNSUPPORTED(SettingExpr)

  // VISIT(WindowExpr) {
  //     frame = ctx->winFrameClause()
  //     visited_frame = visit(frame) if frame else None
  //     expr = ast.WindowExpr(
  //         partition_by=visit(ctx->winPartitionByClause()) if ctx->winPartitionByClause() else None,
  //         order_by=visit(ctx->winOrderByClause()) if ctx->winOrderByClause() else None,
  //         frame_method="RANGE" if frame and frame.RANGE() else "ROWS" if frame and frame.ROWS() else None,
  //         frame_start=visited_frame[0] if isinstance(visited_frame, tuple) else visited_frame,
  //         frame_end=visited_frame[1] if isinstance(visited_frame, tuple) else None,
  //     )
  //     return expr
  // }

  VISIT(WinPartitionByClause) { return visit(ctx->columnExprList()); }

  VISIT(WinOrderByClause) { return visit(ctx->orderExprList()); }

  VISIT(WinFrameClause) { return visit(ctx->winFrameExtend()); }

  VISIT(FrameStart) { return visit(ctx->winFrameBound()); }

  // VISIT(FrameBetween) {
  //     return (visit(ctx->winFrameBound(0)), visit(ctx->winFrameBound(1)))
  // }

  // VISIT(WinFrameBound) {
  //     if (ctx->PRECEDING()) {
  //         return ast.WindowFrameExpr(
  //             frame_type="PRECEDING",
  //             frame_value=visit(ctx->numberLiteral()).value if ctx->numberLiteral() else None,
  //         )
  //     if (ctx->FOLLOWING()) {
  //         return ast.WindowFrameExpr(
  //             frame_type="FOLLOWING",
  //             frame_value=visit(ctx->numberLiteral()).value if ctx->numberLiteral() else None,
  //         )
  //     return ast.WindowFrameExpr(frame_type="CURRENT ROW")

  VISIT(Expr) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnTypeExprSimple)

  VISIT_UNSUPPORTED(ColumnTypeExprNested)

  VISIT_UNSUPPORTED(ColumnTypeExprEnum)

  VISIT_UNSUPPORTED(ColumnTypeExprComplex)

  VISIT_UNSUPPORTED(ColumnTypeExprParam)

  // VISIT(ColumnExprList) {
  //     return [visit(c) for c in ctx->columnExpr()]
  // }

  VISIT(ColumnExprTernaryOp) {
    return build_ast_node(
        state, "Call",
        Py_BuildValue("{s:s, s:[O,O,O]}", "name", "if", "args", any_cast<PyObject*>(visit(ctx->columnExpr(0))),
                      any_cast<PyObject*>(visit(ctx->columnExpr(1))), any_cast<PyObject*>(visit(ctx->columnExpr(2)))));
  }

  // VISIT(ColumnExprAlias) {
  //     if (ctx->alias()) {
  //         alias = visit(ctx->alias())
  //     } else if (ctx->identifier()) {
  //         alias = visit(ctx->identifier())
  //     } else if (ctx->STRING_LITERAL()) {
  //         alias = parse_string_literal(ctx->STRING_LITERAL())
  //     } else {
  //         raise NotImplementedException(f"Must specify an alias")
  //     expr = visit(ctx->columnExpr())

  //     if (alias in RESERVED_KEYWORDS) {
  //         raise HogQLException(f"Alias '{alias}' is a reserved keyword")

  //     return ast.Alias(expr=expr, alias=alias)
  // }

  VISIT_UNSUPPORTED(ColumnExprExtract)

  // VISIT(ColumnExprNegate) {
  //     return ast.ArithmeticOperation(
  //         op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=0), right=visit(ctx->columnExpr())
  //     )
  // }

  VISIT(ColumnExprSubquery) { return visit(ctx->selectUnionStmt()); }

  // VISIT(ColumnExprArray) {
  //     return ast.Array(exprs=visit(ctx->columnExprList()) if ctx->columnExprList() else [])
  // }

  VISIT_UNSUPPORTED(ColumnExprSubstring)

  VISIT_UNSUPPORTED(ColumnExprCast)

  // VISIT(ColumnExprPrecedence1) {
  //     if (ctx->SLASH()) {
  //         op = ast.ArithmeticOperationOp.Div
  //     } else if (ctx->ASTERISK()) {
  //         op = ast.ArithmeticOperationOp.Mult
  //     } else if (ctx->PERCENT()) {
  //         op = ast.ArithmeticOperationOp.Mod
  //     } else {
  //         raise NotImplementedException(f"Unsupported ColumnExprPrecedence1: {ctx->operator.text}")
  //     left = visit(ctx->left)
  //     right = visit(ctx->right)
  //     return ast.ArithmeticOperation(left=left, right=right, op=op)
  // }

  // VISIT(ColumnExprPrecedence2) {
  //     left = visit(ctx->left)
  //     right = visit(ctx->right)

  //     if (ctx->PLUS()) {
  //         return ast.ArithmeticOperation(left=left, right=right, op=ast.ArithmeticOperationOp.Add)
  //     } else if (ctx->DASH()) {
  //         return ast.ArithmeticOperation(left=left, right=right, op=ast.ArithmeticOperationOp.Sub)
  //     } else if (ctx->CONCAT()) {
  //         args = []
  //         if (isinstance(left, ast.Call) and left.name == "concat") {
  //             args.extend(left.args)
  //         } else {
  //             args.append(left)

  //         if (isinstance(right, ast.Call) and right.name == "concat") {
  //             args.extend(right.args)
  //         } else {
  //             args.append(right)

  //         return ast.Call(name="concat", args=args)
  //     } else {
  //         raise NotImplementedException(f"Unsupported ColumnExprPrecedence2: {ctx->operator.text}")
  // }

  VISIT(ColumnExprPrecedence3) {
    PyObject* left = any_cast<PyObject*>(visit(ctx->left));
    PyObject* right = any_cast<PyObject*>(visit(ctx->right));

    PyObject* op = NULL;
    if (ctx->EQ_SINGLE() || ctx->EQ_DOUBLE()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "Eq");
    } else if (ctx->NOT_EQ()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "NotEq");
    } else if (ctx->LT()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "Lt");
    } else if (ctx->LT_EQ()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "LtEq");
    } else if (ctx->GT()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "Gt");
    } else if (ctx->GT_EQ()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "GtEq");
    } else if (ctx->LIKE()) {
      if (ctx->NOT()) {
        op = get_ast_enum_val(state, "CompareOperationOp", "NotLike");
      } else {
        op = get_ast_enum_val(state, "CompareOperationOp", "Like");
      }
    } else if (ctx->ILIKE()) {
      if (ctx->NOT()) {
        op = get_ast_enum_val(state, "CompareOperationOp", "NotILike");
      } else {
        op = get_ast_enum_val(state, "CompareOperationOp", "NotILike");
      }
    } else if (ctx->REGEX_SINGLE() or ctx->REGEX_DOUBLE()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "Regex");
    } else if (ctx->NOT_REGEX()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "NotRegex");
    } else if (ctx->IREGEX_SINGLE() or ctx->IREGEX_DOUBLE()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "IRegex");
    } else if (ctx->NOT_IREGEX()) {
      op = get_ast_enum_val(state, "CompareOperationOp", "NotIRegex");
    } else if (ctx->IN()) {
      if (ctx->COHORT()) {
        if (ctx->NOT()) {
          op = get_ast_enum_val(state, "CompareOperationOp", "NotInCohort");
        } else {
          op = get_ast_enum_val(state, "CompareOperationOp", "InCohort");
        }
      } else {
        if (ctx->NOT()) {
          op = get_ast_enum_val(state, "CompareOperationOp", "NotIn");
        } else {
          op = get_ast_enum_val(state, "CompareOperationOp", "In");
        }
      }
    } else {
      PyErr_SetString(PyExc_NotImplementedError, "Unsupported value of rule ColumnExprPrecedence3");
    }

    return build_ast_node(state, "CompareOperation",
                          Py_BuildValue("{s:O, s:O, s:O}", "left", left, "right", right, "op", op));
  }

  // VISIT(ColumnExprInterval) {
  //     if (ctx->interval().SECOND()) {
  //         name = "toIntervalSecond"
  //     } else if (ctx->interval().MINUTE()) {
  //         name = "toIntervalMinute"
  //     } else if (ctx->interval().HOUR()) {
  //         name = "toIntervalHour"
  //     } else if (ctx->interval().DAY()) {
  //         name = "toIntervalDay"
  //     } else if (ctx->interval().WEEK()) {
  //         name = "toIntervalWeek"
  //     } else if (ctx->interval().MONTH()) {
  //         name = "toIntervalMonth"
  //     } else if (ctx->interval().QUARTER()) {
  //         name = "toIntervalQuarter"
  //     } else if (ctx->interval().YEAR()) {
  //         name = "toIntervalYear"
  //     } else {
  //         raise NotImplementedException(f"Unsupported interval type: {ctx->interval().getText()}")

  //     return ast.Call(name=name, args=[visit(ctx->columnExpr())])
  // }

  VISIT(ColumnExprIsNull) {
    return build_ast_node(
        state, "CompareOperation",
        Py_BuildValue("{s:O, s:O, s:O}", "left", any_cast<PyObject*>(visit(ctx->columnExpr())), "right",
                      build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", Py_None)), "op",
                      get_ast_enum_val(state, "CompareOperationOp", ctx->NOT() ? "NotEq" : "Eq")));
  }

  VISIT_UNSUPPORTED(ColumnExprTrim)

  // VISIT(ColumnExprTuple) {
  //     return ast.Tuple(exprs=visit(ctx->columnExprList()) if ctx->columnExprList() else [])
  // }

  // VISIT(ColumnExprArrayAccess) {
  //     object: ast.Expr = visit(ctx->columnExpr(0))
  //     property: ast.Expr = visit(ctx->columnExpr(1))
  //     if (isinstance(property, ast.Constant) and property.value == 0) {
  //         raise SyntaxException("SQL indexes start from one, not from zero. E.g: array[1]")
  //     return ast.ArrayAccess(array=object, property=property)
  // }

  // VISIT(ColumnExprPropertyAccess) {
  //     object = visit(ctx->columnExpr())
  //     property = ast.Constant(value=visit(ctx->identifier()))
  //     return ast.ArrayAccess(array=object, property=property)
  // }

  VISIT_UNSUPPORTED(ColumnExprBetween)

  VISIT(ColumnExprParens) { return visit(ctx->columnExpr()); }

  VISIT_UNSUPPORTED(ColumnExprTimestamp)

  // VISIT(ColumnExprAnd) {
  //     left = visit(ctx->columnExpr(0))
  //     if (isinstance(left, ast.And)) {
  //         left_array = left.exprs
  //     } else {
  //         left_array = [left]

  //     right = visit(ctx->columnExpr(1))
  //     if (isinstance(right, ast.And)) {
  //         right_array = right.exprs
  //     } else {
  //         right_array = [right]

  //     return ast.And(exprs=left_array + right_array)
  // }

  // VISIT(ColumnExprOr) {
  //     left = visit(ctx->columnExpr(0))
  //     if (isinstance(left, ast.Or)) {
  //         left_array = left.exprs
  //     } else {
  //         left_array = [left]

  //     right = visit(ctx->columnExpr(1))
  //     if (isinstance(right, ast.Or)) {
  //         right_array = right.exprs
  //     } else {
  //         right_array = [right]

  //     return ast.Or(exprs=left_array + right_array)
  // }

  // VISIT(ColumnExprTupleAccess) {
  //     tuple = visit(ctx->columnExpr())
  //     index = int(ctx->DECIMAL_LITERAL().getText())
  //     if (index == 0) {
  //         raise SyntaxException("SQL indexes start from one, not from zero. E.g: array[1]")
  //     return ast.TupleAccess(tuple=tuple, index=index)
  // }

  // VISIT(ColumnExprCase) {
  //     columns = [visit(column) for column in ctx->columnExpr()]
  //     if (ctx->caseExpr) {
  //         args = [columns[0], ast.Array(exprs=[]), ast.Array(exprs=[]), columns[-1]]
  //         for index, column in enumerate(columns):
  //             if (0 < index < len(columns) - 1) {
  //                 args[((index - 1) % 2) + 1].exprs.append(column)
  //         return ast.Call(name="transform", args=args)
  //     } else if (len(columns) == 3) {
  //         return ast.Call(name="if", args=columns)
  //     } else {
  //         return ast.Call(name="multiIf", args=columns)
  // }

  VISIT_UNSUPPORTED(ColumnExprDate)

  VISIT(ColumnExprNot) {
    return build_ast_node(state, "Not", Py_BuildValue("{s:O}", "expr", any_cast<PyObject*>((ctx->columnExpr()))));
  }

  // VISIT(ColumnExprWinFunctionTarget) {
  //     return ast.WindowFunction(
  //         name=visit(ctx->identifier(0)),
  //         args=visit(ctx->columnExprList()) if ctx->columnExprList() else [],
  //         over_identifier=visit(ctx->identifier(1)),
  //     )
  // }

  // VISIT(ColumnExprWinFunction) {
  //     return ast.WindowFunction(
  //         name=visit(ctx->identifier()),
  //         args=visit(ctx->columnExprList()) if ctx->columnExprList() else [],
  //         over_expr=visit(ctx->windowExpr()) if ctx->windowExpr() else None,
  //     )
  // }

  VISIT(ColumnExprIdentifier) { return visit(ctx->columnIdentifier()); }

  // VISIT(ColumnExprFunction) {
  //     name = visit(ctx->identifier())
  //     column_expr_list = ctx->columnExprList()
  //     parameters = visit(column_expr_list) if column_expr_list is not None else None
  //     column_arg_list = ctx->columnArgList()
  //     args = visit(column_arg_list) if column_arg_list is not None else []
  //     distinct = True if ctx->DISTINCT() else False
  //     return ast.Call(name=name, params=parameters, args=args, distinct=distinct)
  // }

  // VISIT(ColumnExprAsterisk) {
  //     if (ctx->tableIdentifier()) {
  //         table = visit(ctx->tableIdentifier())
  //         return ast.Field(chain=table + ["*"])
  //     return ast.Field(chain=["*"])
  // }

  // VISIT(ColumnArgList) {
  //     return [visit(arg) for arg in ctx->columnArgExpr()]
  // }

  // VISIT(ColumnLambdaExpr) {
  //     return ast.Lambda(
  //         args=[visit(identifier) for identifier in ctx->identifier()], expr=visit(ctx->columnExpr())
  //     )
  // }

  // VISIT(WithExprList) {
  //     ctes: Dict[str, ast.CTE] = {}
  //     for expr in ctx->withExpr():
  //         cte = visit(expr)
  //         ctes[cte.name] = cte
  //     return ctes
  // }

  // VISIT(WithExprSubquery) {
  //     subquery = visit(ctx->selectUnionStmt())
  //     name = visit(ctx->identifier())
  //     return ast.CTE(name=name, expr=subquery, cte_type="subquery")
  // }

  // VISIT(WithExprColumn) {
  //     expr = visit(ctx->columnExpr())
  //     name = visit(ctx->identifier())
  //     return ast.CTE(name=name, expr=expr, cte_type="column")
  // }

  VISIT(ColumnIdentifier) {
    auto placeholder = ctx->PLACEHOLDER();

    if (placeholder) {
      string placeholder_string = parse_string_literal(placeholder);
      return build_ast_node(state, "Placeholder",
                            Py_BuildValue("{s:s#}", "field", placeholder_string.c_str(), placeholder_string.size()));
    }

    auto tableIdentifier = ctx->tableIdentifier();
    auto nestedIdentifier = ctx->nestedIdentifier();
    vector<string> table = tableIdentifier ? any_cast<vector<string>>(visit(tableIdentifier)) : vector<string>();
    vector<string> nested = nestedIdentifier ? any_cast<vector<string>>(visit(nestedIdentifier)) : vector<string>();

    if (table.size() == 0 && nested.size() > 0) {
      string text = ctx->getText();
      boost::algorithm::to_lower(text);
      if (!text.compare("true")) {
        auto node = build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", Py_True));
        assert(node);
        return node;
      }
      if (!text.compare("false")) {
        return build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", Py_False));
      }
      return build_ast_node(state, "Field", Py_BuildValue("{s:O}", "chain", vector_to_list_string(nested)));
    }
    vector<string> table_plus_nested = table;
    table_plus_nested.insert(table_plus_nested.end(), nested.begin(), nested.end());
    return build_ast_node(state, "Field", Py_BuildValue("{s:O}", "chain", vector_to_list_string(table_plus_nested)));
  }

  VISIT(NestedIdentifier) {
    vector<string> result;
    for (auto identifier : ctx->identifier()) {
      result.push_back(any_cast<string>(visit(identifier)));
    }
    return result;
  }

  // VISIT(TableExprIdentifier) {
  //     chain = visit(ctx->tableIdentifier())
  //     return ast.Field(chain=chain)
  // }

  VISIT(TableExprSubquery) { return visit(ctx->selectUnionStmt()); }

  // VISIT(TableExprPlaceholder) {
  //     return ast.Placeholder(field=parse_string_literal(ctx->PLACEHOLDER()))
  // }

  // VISIT(TableExprAlias) {
  //     alias = visit(ctx->alias() or ctx->identifier())
  //     if (alias in RESERVED_KEYWORDS) {
  //         raise HogQLException(f"Alias '{alias}' is a reserved keyword")
  //     table = visit(ctx->tableExpr())
  //     if (isinstance(table, ast.JoinExpr)) {
  //         table.alias = alias
  //         return table
  //     return ast.JoinExpr(table=table, alias=alias)
  // }

  VISIT(TableExprFunction) { return visit(ctx->tableFunctionExpr()); }

  // VISIT(TableFunctionExpr) {
  //     name = visit(ctx->identifier())
  //     args = visit(ctx->tableArgList()) if ctx->tableArgList() else []
  //     return ast.JoinExpr(table=ast.Field(chain=[name]), table_args=args)
  // }

  VISIT(TableIdentifier) {
    auto text = any_cast<string>(visit(ctx->identifier()));
    auto databaseIdentifier = ctx->databaseIdentifier();
    if (databaseIdentifier) {
      return vector<string>{any_cast<string>(visit(databaseIdentifier)), text};
    }
    return vector<string>{text};
  }

  VISIT(TableArgList) {
    vector<PyObject*> result;
    for (auto arg : ctx->columnExpr()) {
      result.push_back(any_cast<PyObject*>(visit(arg)));
    }
    return result;
  }

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
      result = build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", value));
      Py_DECREF(pyText);
    } else {
      value = PyLong_FromString(text.c_str(), NULL, 10);
      result = build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", value));
    }

    Py_DECREF(value);

    return result;
  }

  VISIT(Literal) {
    if (ctx->NULL_SQL()) {
      return build_ast_node(state, "Constant", Py_BuildValue("{s:O}", "value", Py_None));
    }
    auto string_literal = ctx->STRING_LITERAL();
    if (string_literal) {
      auto text = parse_string_literal(string_literal);
      return build_ast_node(state, "Constant", Py_BuildValue("{s:s#}", "value", text.c_str(), text.size()));
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
        return parse_string(text);
      }
    }
    return text;
  }

  VISIT(Identifier) {
    string text = ctx->getText();
    if (text.size() >= 2) {
      char first = text[0];
      char last = text[text.size() - 1];
      if ((first == '`' && last == '`') || (first == '"' && last == '"')) {
        return parse_string(text);
      }
    }
    return text;
  }

  VISIT_UNSUPPORTED(EnumValue)

  VISIT(ColumnExprNullish) {
    return build_ast_node(
        state, "Call",
        Py_BuildValue("{s:s, s:[O,O]}", "name", "ifNull", "args", any_cast<PyObject*>(visit(ctx->columnExpr(0))),
                      any_cast<PyObject*>(visit(ctx->columnExpr(1)))));
  }
};

HogQLParser get_parser(const char* statement) {
  auto inputStream = new antlr4::ANTLRInputStream(statement, strnlen(statement, 65536));
  auto lexer = new HogQLLexer(inputStream);
  auto stream = new antlr4::CommonTokenStream(lexer);
  return HogQLParser(stream);
}

static PyObject* parse_expr(PyObject* self, PyObject* args) {
  const char* statement;
  if (!PyArg_ParseTuple(args, "s", &statement)) {
    return NULL;
  }
  HogQLParser parser = get_parser(statement);
  HogQLParser::ExprContext* parseTree = parser.expr();  // TODO: Handle syntax errors
  HogQLParseTreeConverter converter = HogQLParseTreeConverter(GET_STATE(self));
  any result = converter.visit(parseTree);
  try {
    return any_cast<PyObject*>(result);
  } catch (const bad_any_cast& e) {
    PyErr_SetString(PyExc_RuntimeError, "Parsing failed to result in a Python object");
    return NULL;
  }
}

// MODULE SETUP

static PyMethodDef parser_methods[] = {{.ml_name = "parse_expr",
                                        .ml_meth = parse_expr,
                                        .ml_flags = METH_VARARGS,
                                        .ml_doc = "Parse the HogQL expression string into an AST"},
                                       {.ml_name = "parse_select",
                                        .ml_meth = parse_expr,  // TODO
                                        .ml_flags = METH_VARARGS,
                                        .ml_doc = "Parse the HogQL SELECT statement string into an AST"},
                                       {NULL, NULL, 0, NULL}};

static int parser_modexec(PyObject* module) {
  parser_state* state = GET_STATE(module);
  state->ast_module = PyImport_ImportModule("posthog.hogql.ast");
  if (!state->ast_module) {
    return -1;
  }
  return 0;
}

static PyModuleDef_Slot parser_slots[] = {
    // If Python were written in C++, then this would be typed better, but because it's in C, it expects a void pointer
    // This is safe because Python knows what to do subsequently
    {Py_mod_exec, (void*)parser_modexec},
    {0, NULL}};

static int parser_traverse(PyObject* module, visitproc visit, void* arg) {
  parser_state* state = GET_STATE(module);
  Py_VISIT(state->ast_module);
  return 0;
}

static int parser_clear(PyObject* module) {
  parser_state* state = GET_STATE(module);
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
