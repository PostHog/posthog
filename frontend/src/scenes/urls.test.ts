import { urls } from './urls'

describe('urls', () => {
    it('links to the web analytics recap scene', () => {
        expect(urls.webAnalyticsRecap()).toEqual('/web/recap')
    })

    it('percent-encodes property definition ids so virtual ($builtin_*) ids survive route matching', () => {
        expect(urls.propertyDefinition('$builtin_$virt_bot_name')).toEqual(
            '/data-management/properties/%24builtin_%24virt_bot_name'
        )
        expect(urls.propertyDefinitionEdit('$builtin_$virt_bot_name')).toEqual(
            '/data-management/properties/%24builtin_%24virt_bot_name/edit'
        )
        expect(urls.propertyDefinition(':id')).toEqual('/data-management/properties/:id')
    })

    it.each(['Postgres', 'MySQL', 'Snowflake'] as const)(
        'includes direct access method when opening the new %s source wizard in direct mode',
        (sourceType) => {
            expect(urls.dataWarehouseSourceNew(sourceType, undefined, undefined, 'direct')).toEqual(
                `/data-warehouse/new-source?kind=${sourceType}&access_method=direct`
            )
        }
    )
})
