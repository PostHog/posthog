import { LemonSelect, LemonSelectOption, LemonSelectProps } from '@posthog/lemon-ui'

import { AccessControlLevel } from '~/types'

import type { InheritedAccess } from './accessControlLogic'
import { humanizeAccessControlLevel } from './ResourceAccessControlsV2/helpers'

export interface AccessLevelSelectProps {
    size?: LemonSelectProps<any>['size']
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

    return (
        <LemonSelect<AccessControlLevel | null>
            size={props.size}
            placeholder="Select level..."
            value={props.level}
            onChange={props.onChange}
            disabledReason={props.disabledReason}
            dropdownMatchSelectWidth={false}
            // The trigger sits at the right edge of its row, so hang the menu off that edge
            dropdownPlacement="bottom-end"
            tooltip={
                inherited
                    ? props.level === null
                        ? inherited.reason
                        : `Overrides ${inherited.label}. ${inherited.reason}.`
                    : undefined
            }
            renderButtonContent={
                noOverrideLabel ? (leaf) => (props.level === null ? noOverrideLabel : (leaf?.label ?? '')) : undefined
            }
            options={
                inherited
                    ? [
                          {
                              options: [
                                  {
                                      value: null,
                                      label: 'No override',
                                      labelInMenu: (
                                          <div className="flex flex-col items-start gap-1 py-1">
                                              {noOverrideLabel}
                                              <span className="text-xs font-normal text-tertiary whitespace-nowrap">
                                                  {inherited.reason}
                                              </span>
                                          </div>
                                      ),
                                  },
                              ],
                          },
                          { options: levelOptions },
                      ]
                    : levelOptions
            }
        />
    )
}
