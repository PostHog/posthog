// @ts-nocheck
// Test fixture for the toolbar-transport-no-error-tracking rule.

// ruleid: toolbar-transport-no-error-tracking
captureToolbarException(error, 'network', { status: 0 })

// ruleid: toolbar-transport-no-error-tracking
toolbarPosthogJS.captureException(error, { toolbar_context: 'api' })

// ok: toolbar-transport-no-error-tracking
toolbarLogger.error('api', 'Request failed (network)', { context })

// ok: toolbar-transport-no-error-tracking
toolbarPosthogJS.capture('toolbar api request', { status: 0 })
