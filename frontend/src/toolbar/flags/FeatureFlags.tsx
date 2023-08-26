import './featureFlags.scss'

import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { Radio } from 'antd'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import clsx from 'clsx'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'

export function FeatureFlags(): JSX.Element {
    const { searchTerm, filteredFlags } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag, setSearchTerm } = useActions(featureFlagsLogic)
    const { apiURL } = useValues(toolbarLogic)

    return (
        <div className="toolbar-block ToolbarBlock">
            <div className="local-feature-flag-override-note">
                Note, overriding feature flags will only affect this browser.
            </div>
            <>
                <LemonInput
                    autoFocus
                    fullWidth
                    placeholder="Search"
                    value={searchTerm}
                    className={'feature-flag-row'}
                    type="search"
                    onChange={(s) => setSearchTerm(s)}
                />
                <div className={'flex flex-col'}>
                    {filteredFlags.length > 0
                        ? filteredFlags.map(({ feature_flag, value, hasOverride, hasVariants, currentValue }) => {
                              return (
                                  <div key={feature_flag.key} className={'feature-flag-row'}>
                                      <div
                                          className={clsx(
                                              'flex flex-row',
                                              hasOverride
                                                  ? 'feature-flag-row-header overridden'
                                                  : 'feature-flag-row-header'
                                          )}
                                      >
                                          <div className="feature-flag-title">{feature_flag.key}</div>
                                          <a
                                              className="feature-flag-external-link"
                                              href={`${apiURL}${
                                                  feature_flag.id
                                                      ? urls.featureFlag(feature_flag.id)
                                                      : urls.featureFlags()
                                              }`}
                                              target="_blank"
                                              rel="noopener noreferrer"
                                          >
                                              <IconOpenInNew />
                                          </a>
                                          <LemonSwitch
                                              checked={!!currentValue}
                                              onChange={(checked) => {
                                                  const newValue =
                                                      hasVariants && checked
                                                          ? (feature_flag.filters?.multivariate?.variants[0]
                                                                ?.key as string)
                                                          : checked
                                                  if (newValue === value && hasOverride) {
                                                      deleteOverriddenUserFlag(feature_flag.key)
                                                  } else {
                                                      setOverriddenUserFlag(feature_flag.key, newValue)
                                                  }
                                              }}
                                          />
                                      </div>

                                      <AnimatedCollapsible collapsed={!hasVariants || !currentValue}>
                                          <div
                                              className={clsx(
                                                  'flex flex-row',
                                                  hasOverride ? 'variant-radio-group overridden' : 'variant-radio-group'
                                              )}
                                          >
                                              <Radio.Group
                                                  disabled={!currentValue}
                                                  value={currentValue}
                                                  onChange={(event) => {
                                                      const newValue = event.target.value
                                                      if (newValue === value && hasOverride) {
                                                          deleteOverriddenUserFlag(feature_flag.key)
                                                      } else {
                                                          setOverriddenUserFlag(feature_flag.key, newValue)
                                                      }
                                                  }}
                                              >
                                                  {feature_flag.filters?.multivariate?.variants.map((variant) => (
                                                      <Radio key={variant.key} value={variant.key}>
                                                          {`${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`}
                                                      </Radio>
                                                  ))}
                                              </Radio.Group>
                                          </div>
                                      </AnimatedCollapsible>
                                  </div>
                              )
                          })
                        : 'No feature flags found'}
                </div>
            </>
        </div>
    )
}
