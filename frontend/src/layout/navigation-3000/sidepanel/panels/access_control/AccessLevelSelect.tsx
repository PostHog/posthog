import { LemonSelect, LemonSelectOption, LemonSelectProps } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import type { InheritedAccess } from './accessControlLogic'
import { humanizeAccessControlLevel } from './ResourceAccessControlsV2/helpers'

export interface AccessLevelSelectProps {
    size?: LemonSelectProps<any>['size']
    fullWidth?: boolean
    /** Pass "bottom-end" when the trigger sits at the right edge of a row, so the wider menu
     * hangs inward instead of off the edge. Left-positioned triggers keep the default. */
    dropdownPlacement?: LemonSelectProps<any>['dropdownPlacement']
    /** The subject's own saved rule; null means no rule ("No override"). */
    level: AccessControlLevel | null
    levels: AccessControlLevel[]
    onChange: (newValue: AccessControlLevel | null) => void
    disabledReason?: string
    /** Levels below this are offered but disabled. */
    minimumLevel?: AccessControlLevel | null
    /**
     * What applies when there is no rule. Passing it offers "No override" as a way back,
     * rendered as `No override · <level>` with the reason in the tooltip and menu entry.
     */
    inherited?: InheritedAccess | null
    /**
     * Offer a plain "No override" option without annotating what applies instead — for levels
     * where resolving the fallback isn't reliable yet.
     */
    allowNoOverride?: boolean
}

/** Access level dropdown where "no rule" is a real, selectable state that shows what it falls back to. */
export function AccessLevelSelect(props: AccessLevelSelectProps): JSX.Element {
    const { inherited } = props

    // The trigger and the menu entry read identically, so what you pick is what you end up looking at.
    // The inherited half drops to the button's normal weight so it reads as a consequence, not a second value.
    const noOverrideLabel = inherited ? (
        <span className="whitespace-nowrap">
            No override <span className="font-normal text-tertiary">· {inherited.label}</span>
        </span>
    ) : null

    const levelOptions: LemonSelectOption<AccessControlLevel | null>[] = props.levels.map((level) => {
        const isDisabled = props.minimumLevel
            ? props.levels.indexOf(level) < props.levels.indexOf(props.minimumLevel)
            : false
        return {
            value: level,
            label: humanizeAccessControlLevel(level),
            disabledReason: isDisabled ? 'Not available for this resource type' : undefined,
        }
    })

    // "No override" sits in its own section above the levels: annotated with what applies instead
    // when we know it (`inherited`), plain when we don't (`allowNoOverride`).
    let options: LemonSelectOption<AccessControlLevel | null>[] | { options: typeof levelOptions }[] = levelOptions
    if (inherited) {
        const noOverrideOption = {
            value: null,
            label: 'No override',
            labelInMenu: (
                <div className="flex flex-col items-start gap-1 py-1">
                    {noOverrideLabel}
                    <span className="text-xs font-normal text-tertiary whitespace-nowrap">{inherited.reason}</span>
                </div>
            ),
        }
        options = [{ options: [noOverrideOption] }, { options: levelOptions }]
    } else if (props.allowNoOverride) {
        options = [{ options: [{ value: null, label: 'No override' }] }, { options: levelOptions }]
    }

    return (
        <LemonSelect<AccessControlLevel | null>
            size={props.size}
            fullWidth={props.fullWidth}
            dropdownMatchSelectWidth={props.fullWidth ?? false}
            placeholder="Select level..."
            value={props.level}
            onChange={props.onChange}
            disabledReason={props.disabledReason}
            dropdownPlacement={props.dropdownPlacement}
            tooltip={
                // A disabled control explains itself through disabledReason; adding the inherited
                // reason on top reads as two unrelated sentences
                props.disabledReason || !inherited
                    ? undefined
                    : props.level === null
                      ? inherited.reason
                      : `Overrides ${inherited.label}. ${inherited.reason}.`
            }
            renderButtonContent={
                noOverrideLabel ? (leaf) => (props.level === null ? noOverrideLabel : (leaf?.label ?? '')) : undefined
            }
            options={options}
        />
    )
}
