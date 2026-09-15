# Experiment query errors

Experiment metrics that fail a `throwIf` guard show the guard's error message and ask the user to check the metric configuration.
HogQL expressions that reference a column outside an aggregate show guidance to wrap the value in an aggregation.

The experiment error handler converts these known configuration errors to `UserQueryValidationError`.
This subtype preserves DRF's validation response, including HTTP 400, the `invalid` code, and the error detail format used by asynchronous query polling.
The shared query classifier treats it as `user_error`, so the outer query runner excludes it from error tracking and platform failure accounting.
The experiment metric error event still records the user-visible failure as `validation_error`.

Use `UserQueryValidationError` only when user query configuration is the known cause.
Other DRF `ValidationError` instances keep their existing classification because the experiment handler also uses them to present platform errors.

Internal callers, including recalculation and timeseries, receive the original ClickHouse exception.
The experiment classifier treats ClickHouse codes 395 (`FUNCTION_THROW_IF_VALUE_IS_NON_ZERO`) and 215 (`NOT_AN_AGGREGATE`) as `validation_error`, so recalculation does not retry them.
