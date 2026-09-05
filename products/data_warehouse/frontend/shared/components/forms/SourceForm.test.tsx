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

// A sensitive field reloads blank because the backend redacts it. Report the placeholder the input
// shows and whether the field renders help — the bug was a bare empty box with neither.
const scalarFieldRender = (
    field: SourceFieldInputConfig,
    isUpdateMode?: boolean
): { placeholder: string | undefined; hasHelp: boolean } => {
    const element = sourceFieldToElement(field, SOURCE_CONFIG, undefined, isUpdateMode)
    const input = element.props.children({ value: '', onChange: jest.fn() })
    return { placeholder: input.props.placeholder, hasHelp: !!element.props.help }
}

// Reads the credential help sentence(s) a masked field renders in update mode. The webhook form
// reuses this renderer, and its secrets must not claim a connection change requires re-entering them.
const credentialHelpText = (field: SourceFieldInputConfig, fieldContext?: 'source' | 'webhook'): string => {
    const element = sourceFieldToElement(field, SOURCE_CONFIG, undefined, true, undefined, undefined, fieldContext)
    const helpChildren = element.props.help.props.children
    const span = (Array.isArray(helpChildren) ? helpChildren : [helpChildren]).find(
        (child: any) => child?.props?.className === 'text-xs'
    )
    const spanChildren = Array.isArray(span.props.children) ? span.props.children : [span.props.children]
    return spanChildren.filter((child: any) => typeof child === 'string').join('')
}

const SECRET_FIELD: SourceFieldInputConfig = {
    type: 'password',
    name: 'api_key',
    label: 'API key',
    required: true,
    // AppLovin's Report Key ships an empty placeholder, so the unfixed box was completely bare.
    placeholder: '',
    secret: true,
}

describe('sourceFieldToElement', () => {
    it('masks a saved secret and explains that blank keeps it when editing a source', () => {
        const { placeholder, hasHelp } = scalarFieldRender(SECRET_FIELD, true)
        expect(placeholder).not.toBe('')
        expect(hasHelp).toBe(true)
    })

    it('shows the plain placeholder for a secret field on a new source', () => {
        expect(scalarFieldRender(SECRET_FIELD, false)).toEqual({ placeholder: '', hasHelp: false })
    })

    // An optional secret (e.g. openFDA's api_key) may never have been saved, and the redacted
    // response can't say. Masking it would claim a stored value that may not exist, so it keeps its
    // own placeholder and no keep-value help even when editing.
    it('does not mask an optional secret when editing a source', () => {
        const optionalSecret: SourceFieldInputConfig = {
            ...SECRET_FIELD,
            required: false,
            placeholder: 'Your API key',
        }
        expect(scalarFieldRender(optionalSecret, true)).toEqual({ placeholder: 'Your API key', hasHelp: false })
    })

    // The webhook config form reuses this renderer with isUpdateMode true. Its secrets live in the
    // webhook's own inputs, so the source connection-change caveat is wrong there; show it only for
    // source credentials.
    it.each([
        ['source' as const, true],
        ['webhook' as const, false],
    ])('shows the connection-change caveat only for %s credentials', (fieldContext, expectCaveat) => {
        const text = credentialHelpText(SECRET_FIELD, fieldContext)
        expect(text).toContain('Leave blank to keep the saved value')
        expect(text.includes('you change the connection details')).toBe(expectCaveat)
    })

    it('does not mask a non-sensitive field when editing a source', () => {
        const hostField: SourceFieldInputConfig = {
            type: 'text',
            name: 'host',
            label: 'Host',
            required: true,
            placeholder: 'localhost',
            secret: false,
        }
        expect(scalarFieldRender(hostField, true)).toEqual({ placeholder: 'localhost', hasHelp: false })
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
