import { SourceConfig, SourceFieldSelectConfig } from '~/queries/schema/schema-general'

import { sourceFieldToElement } from './SourceForm'

const SELECT_FIELD: SourceFieldSelectConfig = {
    type: 'select',
    name: 'response_types',
    label: 'Responses to sync',
    required: false,
    defaultValue: 'completed',
    options: [
        { label: 'Completed responses only', value: 'completed' },
        { label: 'All responses (including partial & started)', value: 'completed,partial,started' },
    ],
    caption: 'Changing this triggers a full refresh of the responses table.',
}

const SOURCE_CONFIG = { name: 'Typeform', fields: [] } as unknown as SourceConfig

describe('sourceFieldToElement', () => {
    it('renders a select field caption as field help text', () => {
        const element = sourceFieldToElement(SELECT_FIELD, SOURCE_CONFIG)
        expect(element.props.help).toBeTruthy()
    })

    it('omits help when a select field has no caption', () => {
        const element = sourceFieldToElement({ ...SELECT_FIELD, caption: undefined }, SOURCE_CONFIG)
        expect(element.props.help).toBeUndefined()
    })
})
