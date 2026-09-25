# AI evaluation report comparisons

Numeric evaluation reports calculate current and previous period metrics using the report's current passing rule.
These metrics are the basis for statements about changes in pass rate.
N/A results are excluded from the pass-rate denominator.

Previously generated reports retain their saved metrics and passing rules.
Their snapshot rates can differ from recalculated previous-period rates after a threshold change.
The report agent's history index includes each numeric report's output configuration and whether its passing rule matches the current rule.
A missing rule is treated as unknown, rather than as a matching rule.
The agent must explain a rule change separately from a performance change.

For Hog evaluations, report context includes the source code as evaluation criteria.
The agent reads it to interpret the score, including unit conversions, without executing it.
Hog evaluations do not have to provide reasoning; an empty reason alone does not indicate broken instrumentation.
