import {
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldSelectConfig,
    SourceFieldSwitchGroupConfig,
} from '~/queries/schema/schema-general'

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

const SWITCH_GROUP_FIELD: SourceFieldSwitchGroupConfig = {
    type: 'switch-group',
    name: 'custom_properties',
    label: 'Customize synced properties',
    default: false,
    fields: [
        {
            type: 'textarea',
            name: 'deals_properties',
            label: 'Deals properties',
            required: false,
            placeholder: '',
            secret: false,
        },
    ],
}

// Renders the switch group and reports the toggle's checked state alongside whether its child
// fields expanded — the bug was precisely those two disagreeing.
const switchGroupState = (storedGroupValue: any, formValue?: any): { checked: boolean; childrenVisible: boolean } => {
    const element = sourceFieldToElement(SWITCH_GROUP_FIELD, SOURCE_CONFIG, storedGroupValue)
    const rendered = element.props.children({ value: formValue, onChange: jest.fn() })
    const children = Array.isArray(rendered.props.children) ? rendered.props.children : [rendered.props.children]
    const toggle = children.find((child: any) => child && child.props && 'checked' in child.props)
    if (!toggle) {
        throw new Error('switch group rendered no toggle')
    }
    return { checked: toggle.props.checked, childrenVisible: !!children.find((child: any) => child?.props?.name) }
}

const CONNECTION_STRING_FIELD: SourceFieldInputConfig = {
    type: 'text',
    name: 'connection_string',
    label: 'Connection String',
    required: true,
    // tls=true keeps the trailofbits mongodb-insecure-transport semgrep rule happy; the value is
    // never asserted, so don't drop it back to a bare mongodb:// string.
    placeholder: 'mongodb://host:port/db?tls=true',
    secret: true,
}

// Finds the connection_string LemonInput inside the field's rendered fragment and returns it.
const renderConnectionStringInput = (isUpdateMode: boolean): any => {
    const fragment = sourceFieldToElement(CONNECTION_STRING_FIELD, SOURCE_CONFIG, undefined, isUpdateMode)
    const children = Array.isArray(fragment.props.children) ? fragment.props.children : [fragment.props.children]
    const field = children.find((child: any) => child?.props?.name === 'connection_string')
    if (!field) {
        throw new Error('connection string field did not render')
    }
    return { field, input: field.props.children({ value: '', onChange: jest.fn() }) }
}

describe('sourceFieldToElement', () => {
    // Rotating a connection-string credential used to require deleting and recreating the source,
    // because the field was suppressed entirely on update. It must now render as an editable,
    // password-style input that starts blank (an empty value keeps the stored secret server-side).
    it('renders the connection string as an editable password input on update', () => {
        const { field, input } = renderConnectionStringInput(true)
        expect(input.props.type).toBe('password')
        expect(field.props.help).toContain('Leave blank')
    })

    it('renders the connection string as a text input without help on create', () => {
        const { field, input } = renderConnectionStringInput(false)
        expect(input.props.type).toBe('text')
        expect(field.props.help).toBeUndefined()
    })

    it('renders a select field caption as field help text', () => {
        const element = sourceFieldToElement(SELECT_FIELD, SOURCE_CONFIG)
        expect(element.props.help).toBeTruthy()
    })

    it('omits help when a select field has no caption', () => {
        const element = sourceFieldToElement({ ...SELECT_FIELD, caption: undefined }, SOURCE_CONFIG)
        expect(element.props.help).toBeUndefined()
    })

    // job_inputs cross an encrypted field that stringifies booleans, so the form prefills `enabled`
    // as "True"/"False". LemonSwitch checks `checked === true`, so an untranslated "True" rendered
    // the toggle off while the truthy string still expanded the children below it.
    it.each([
        ['prefilled as the string True', undefined, 'True', true],
        ['prefilled as the string False', undefined, 'False', false],
        ['toggled on in the form', undefined, true, true],
        ['stored as the string True before the prefill lands', { enabled: 'True' }, undefined, true],
        ['never configured', undefined, undefined, false],
        ['toggled off in the form over a stored True', { enabled: 'True' }, false, false],
    ])('reflects a switch group %s', (_name, storedGroupValue, formValue, expected) => {
        expect(switchGroupState(storedGroupValue, formValue)).toEqual({
            checked: expected,
            childrenVisible: expected,
        })
    })
})
