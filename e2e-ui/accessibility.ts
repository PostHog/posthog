export const violationFingerprints = (accessibilityScanResults: Record<string, any>): string => {
    const violationFingerprints = accessibilityScanResults.violations.map((violation: Record<string, any>) => ({
        rule: violation.id,
        // These are CSS selectors which uniquely identify each element with
        // a violation of the rule in question.
        targets: violation.nodes.map((node) => node.target),
    }))

    return JSON.stringify(violationFingerprints, null, 2)
}
