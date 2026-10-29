import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'

import { PII_MASKING_PRESET_COLORS } from '~/toolbar/shared/bar/piiMaskingStyles'

import { extensionMoreLogic } from '../../logics/panel/extensionMoreLogic'

function ColorSwatch({ color }: { color: string }): JSX.Element {
    return (
        <span
            className="inline-block w-4 h-4 rounded border"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ backgroundColor: color }}
        />
    )
}

/** Previews on the page what session recordings mask, with the page's masking settings. */
export function ExtensionPiiMasking(): JSX.Element {
    const { moreState } = useValues(extensionMoreLogic)
    const { setPiiMasking, sendMoreCommand } = useActions(extensionMoreLogic)
    const enabled = !!moreState?.piiMaskingEnabled

    return (
        <section className="flex flex-col gap-2">
            <h4 className="m-0 text-sm font-semibold">PII masking</h4>
            <LemonSwitch
                fullWidth
                bordered
                label="Hide PII on this page"
                checked={enabled}
                disabledReason={moreState ? null : 'Connecting to the page…'}
                onChange={setPiiMasking}
                data-attr="toolbar-extension-pii-masking"
            />
            {enabled && moreState && (
                <LemonSelect
                    size="small"
                    fullWidth
                    value={moreState.piiMaskingColor}
                    onChange={(color) => sendMoreCommand({ type: 'set-pii-masking-color', color })}
                    options={PII_MASKING_PRESET_COLORS.map(({ label, value }) => ({
                        label,
                        value,
                        icon: <ColorSwatch color={value} />,
                    }))}
                    data-attr="toolbar-extension-pii-masking-color"
                />
            )}
            {moreState?.piiWarnings.map((warning) => (
                <LemonBanner key={warning} type="warning">
                    {warning}
                </LemonBanner>
            ))}
            <div className="text-xs text-secondary">
                Shows on the page which text and elements session recordings mask.
            </div>
        </section>
    )
}
