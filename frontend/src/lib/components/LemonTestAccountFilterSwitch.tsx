import React from 'react'

import { IconExternal, IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonSwitchProps } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

export type LemonTestAccountFilterSwitchProps = Partial<LemonSwitchProps> & {
    checked: boolean
    onChange: (checked: boolean) => void
    onConfigure?: () => void
    showNewTabIcon: boolean
}

export function LemonTestAccountFilterSwitch({
    checked,
    onChange,
    onConfigure,
    showNewTabIcon,
    disabledReason,
    ...props
}: LemonTestAccountFilterSwitchProps): JSX.Element {
    return (
        <LemonSwitch
            id="test-account-filter"
            bordered
            {...props}
            disabledReason={disabledReason}
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    {/* Opens in a new tab by default: this switch sits inside forms that hold unsaved work (a
                        half-built scanner, an unsaved cohort, an insight in progress), and the
                        disabledReason below actively sends people here when no filters are set up.
                        Callers that can configure the filters in place pass onConfigure instead. */}
                    <LemonButton
                        icon={showNewTabIcon ? <IconExternal className="size-3.5" /> : <IconGear />}
                        size="small"
                        noPadding
                        className="ml-1"
                        {...(onConfigure
                            ? {
                                  // The gear sits inside the switch's <label htmlFor>, which forwards clicks to the
                                  // switch button. Stop it here so opening settings can't also flip the filter.
                                  onClick: (e: React.MouseEvent) => {
                                      e.preventDefault()
                                      e.stopPropagation()
                                      onConfigure()
                                  },
                                  tooltip: 'Configure internal and test users.',
                              }
                            : {
                                  to: urls.settings('environment-customization', 'internal-user-filtering'),
                                  targetBlank: true,
                                  hideExternalLinkIcon: true,
                                  tooltip: 'Configure internal and test users. Opens in a new tab.',
                              })}
                    />
                </div>
            }
        />
    )
}
