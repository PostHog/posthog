// @ts-nocheck
// Test fixture for the toolbar-no-capture-on-request-failure rule.

function badNegatedBranch(result) {
    // ruleid: toolbar-no-capture-on-request-failure
    if (!result.ok) {
        toolbarLogger.error('api', 'failed')
        captureToolbarException(new Error(result.error.detail), 'load_actions')
        return []
    }
}

function badElseBranch(result) {
    // ruleid: toolbar-no-capture-on-request-failure
    if (result.ok) {
        return result.data
    } else {
        captureToolbarException(new Error(result.error.detail), 'load_actions')
        return []
    }
}

function okTaggedThrow(result) {
    // ok: toolbar-no-capture-on-request-failure
    if (!result.ok) {
        throw new ToolbarRequestError(result.error.detail, result.status)
    }
    return result.data
}

function okLocalFallback(result) {
    // ok: toolbar-no-capture-on-request-failure
    if (!result.ok) {
        return []
    }
    return result.data.results
}
