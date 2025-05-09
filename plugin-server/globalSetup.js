const { resetTestDatabase } = require('./tests/helpers/sql')
const { createHub } = require('./src/utils/db/hub')
const { TemplateSyncService } = require('./src/cdp/templates/sync-hog-function-templates')

module.exports = async () => {
    try {
        await resetTestDatabase()
    } catch (error) {
        throw error
    }
    const hub = await createHub()
    try {
        const templateSyncService = new TemplateSyncService(hub)
        await templateSyncService.syncTemplates()
    } catch (error) {
        throw error
    }
}
