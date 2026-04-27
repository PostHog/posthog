/**
 * Copy for feature-flag dependency filters ("evaluates to true/false").
 * Values are whether the dependency flag evaluates true or false for the user for this condition to apply.
 */

export function isFlagDependencyBooleanValue(raw: unknown): boolean {
    return raw === true || raw === false || raw === 'true' || raw === 'false'
}

function dependencyFlagEvaluatesTrue(raw: unknown): boolean {
    return raw === true || raw === 'true'
}

/** Short label for dropdowns and snacks */
export function getFlagDependencyValueLabel(raw: unknown): string {
    if (!isFlagDependencyBooleanValue(raw)) {
        return String(raw)
    }
    return dependencyFlagEvaluatesTrue(raw) ? 'Evaluate true' : 'Evaluate false'
}

/** Explains inclusion semantics for the dependency flag value picker */
export function getFlagDependencyValueTooltip(raw: unknown): string | undefined {
    if (!isFlagDependencyBooleanValue(raw)) {
        return undefined
    }
    return dependencyFlagEvaluatesTrue(raw)
        ? 'Include users only when this dependency flag evaluates to true for them.'
        : 'Include users only when this dependency flag evaluates to false for them.'
}
