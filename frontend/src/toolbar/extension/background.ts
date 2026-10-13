import {
    getContentStatus,
    hasHostPermission,
    onBackgroundRequest,
    openTab,
    sendContentCommand,
} from './extensionBrowser'

// Reaches the inspected tab for the DevTools panel, which can't call `tabs` or `scripting` in every browser.
onBackgroundRequest(async (request) => {
    switch (request.type) {
        case 'content-status':
            return await getContentStatus(request.tabId)
        case 'content-command':
            return await sendContentCommand(request.tabId, request.command)
        case 'has-host-permission':
            return await hasHostPermission(request.uiHost)
        case 'open-tab':
            await openTab(request.url)
            return true
    }
})
