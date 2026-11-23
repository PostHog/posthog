export {
    DESCRIPTION_VERSION,
    formatDescription,
    isRefValue,
    sortKeys,
    type ProblemSeverity,
    type RefValue,
    type ResourceDescription,
    type ResourceSource,
    type StackDescription,
    type StackProblem,
} from './description.js'
export { evaluateExports, type EvaluateOptions, type Evaluation, type ResourceOrigin } from './evaluate.js'
export { findRoot, loadStack, sortProblems, type LoadStackOptions, type StackResult } from './load.js'
export {
    KEY_MAX_LENGTH,
    KEY_PATTERN,
    kindSpec,
    knownKinds,
    type IdType,
    type KindSpec,
    type QuerySchema,
    type RefPosition,
    type RuleIssue,
    type SchemaGap,
} from './registry.js'
export { findCompiler, typeCheckStack, type TypeCheckResult } from './typecheck.js'
export {
    validateDescription,
    validateStructure,
    type SchemaValidator,
    type StructureOptions,
    type ValidateOptions,
} from './validate.js'
export { generateDefinitions, type GenerateOptions, type GeneratedFile } from './generate.js'
export { foldDrift, type Drift, type DriftField, type FoldedField, type ManualField } from './fold.js'
