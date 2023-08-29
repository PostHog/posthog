import { useState } from 'react'
import { BindLogic, useActions, useValues } from 'kea'

import { LemonCheckbox, LemonInput, LemonLabel, LemonTag, LemonTagProps } from '@posthog/lemon-ui'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { breakdownTagLogic } from './breakdownTagLogic'
import { BreakdownTagMenu } from './BreakdownTagMenu'
import { BreakdownType, ChartDisplayType } from '~/types'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { PopoverReferenceContext } from 'lib/lemon-ui/Popover/Popover'
import { HoqQLPropertyInfo } from 'lib/components/HoqQLPropertyInfo'
import { cohortsModel } from '~/models/cohortsModel'
import { isAllCohort, isCohort } from './taxonomicBreakdownFilterUtils'

import './BreakdownTag.scss'
import { LemonMenuItems, LemonMenuOverlay } from 'lib/lemon-ui/LemonMenu/LemonMenu'
import { BreakdownFilter } from '~/queries/schema'
import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

type EditableBreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType
    isTrends: boolean
}

const BREAKDOWN_VALUES_LIMIT = 25
const BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES = 300

const Xx = (): JSX.Element => {
    const { breakdownFilter, display, histogramBinCount, histogramBinsUsed } = useValues(taxonomicBreakdownFilterLogic)
    const {
        setHistogramBinCount,
        setHistogramBinsUsed,
        setNormalizeBreakdownURL,
        setBreakdownLimit,
        updateBreakdownFilter,
    } = useActions(taxonomicBreakdownFilterLogic)

    const { isHistogramable, isNormalizeable } = useValues(breakdownTagLogic)
    const { removeBreakdown } = useActions(breakdownTagLogic)

    const { breakdown_histogram_bin_count, breakdown_limit, breakdown_normalize_url } = breakdownFilter

    const defaultBreakdownLimit =
        display !== ChartDisplayType.WorldMap ? BREAKDOWN_VALUES_LIMIT : BREAKDOWN_VALUES_LIMIT_FOR_COUNTRIES
    const isUsingHistogramBins = !!breakdown_histogram_bin_count
    const breakdownLimit = breakdown_limit || defaultBreakdownLimit

    const showPercentStackView = true
    const items: LemonMenuItems = [
        ...(isHistogramable
            ? [
                  {
                      title: 'Numeric values',
                      items: [
                          {
                              label: () => (
                                  <>
                                      <LemonCheckbox
                                          id="histogramBinsUsed"
                                          className="p-1 px-2"
                                          checked={histogramBinsUsed}
                                          onChange={(value) => {
                                              setHistogramBinsUsed(value)
                                          }}
                                          label={
                                              <LemonLabel htmlFor="histogramBinsUsed">Bin numeric values</LemonLabel>
                                          }
                                          size="small"
                                      />
                                      {isUsingHistogramBins ? (
                                          <div className="mt-0.5 mx-2 mb-3">
                                              <LemonInput
                                                  min={1}
                                                  size="small"
                                                  value={histogramBinCount}
                                                  onChange={(count) => {
                                                      setHistogramBinCount(count)
                                                  }}
                                                  type="number"
                                              />
                                          </div>
                                      ) : (
                                          <div className="mx-2 mb-3">
                                              <LemonLabel htmlFor="breakdownLimit">Breakdown values</LemonLabel>
                                              <LemonInput
                                                  id="breakdownLimit"
                                                  min={1}
                                                  size="small"
                                                  value={breakdownLimit}
                                                  onChange={(value) => {
                                                      setBreakdownLimit(value)
                                                  }}
                                                  disabled={isUsingHistogramBins}
                                                  type="number"
                                              />
                                          </div>
                                      )}
                                  </>
                              ),
                          },
                      ],
                  },
              ]
            : []),
        ...(!isUsingHistogramBins
            ? [
                  {
                      title: 'Breakdown values',
                      items: [
                          {
                              label: () => (
                                  <div className="mx-2 mb-3">
                                      <LemonInput
                                          id="breakdownLimit"
                                          min={1}
                                          size="small"
                                          value={breakdownLimit}
                                          onChange={(value) => {
                                              setBreakdownLimit(value)
                                          }}
                                          disabled={isUsingHistogramBins}
                                          type="number"
                                      />
                                  </div>
                              ),
                          },
                      ],
                  },
              ]
            : []),
        ...(isNormalizeable
            ? [
                  {
                      title: 'Normalize paths',
                      items: [
                          {
                              label: () => (
                                  <div>
                                      <LemonCheckbox
                                          id="breakdownNormalizeUrl"
                                          className="p-1 px-2"
                                          checked={breakdown_normalize_url}
                                          onChange={setNormalizeBreakdownURL}
                                          label={
                                              <LemonLabel
                                                  htmlFor="breakdownNormalizeUrl"
                                                  info={
                                                      <>
                                                          <p>
                                                              Strip noise (trailing slashes, question marks, and hashes)
                                                              from paths by enabling this option.
                                                          </p>
                                                          <p>
                                                              Without path normalization, "https://example.com",
                                                              "https://example.com/", "https://example.com/?" and
                                                              "https://example.com/#" are treated as four distinct
                                                              breakdown values. With normalization, they all count
                                                              towards "https://example.com".
                                                          </p>
                                                      </>
                                                  }
                                              >
                                                  Remove trailing slashes
                                              </LemonLabel>
                                          }
                                          size="small"
                                      />
                                  </div>
                              ),
                          },
                      ],
                  },
              ]
            : []),
        {
            items: [
                {
                    label: 'Remove breakdown',
                    onClick: () => {
                        removeBreakdown()
                    },
                    status: 'danger',
                },
            ],
        },
    ]

    return <LemonMenuOverlay items={items} />
}

export function EditableBreakdownTag({ breakdown, breakdownType, isTrends }: EditableBreakdownTagProps): JSX.Element {
    const [filterOpen, setFilterOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const logicProps = { breakdown, breakdownType, isTrends }
    const { shouldShowMenu } = useValues(breakdownTagLogic(logicProps))
    const { removeBreakdown } = useActions(breakdownTagLogic(logicProps))

    return (
        <BindLogic logic={breakdownTagLogic} props={logicProps}>
            <TaxonomicBreakdownPopover open={filterOpen} setOpen={setFilterOpen}>
                <div>
                    {/* :TRICKY: we don't want the close button to be active when the edit popover is open.
                     * Therefore we're wrapping the lemon tag a context provider to override the parent context. */}
                    <PopoverReferenceContext.Provider value={null}>
                        <BreakdownTag
                            breakdown={breakdown}
                            breakdownType={breakdownType}
                            // display remove button only if we can edit and don't have a separate menu
                            closable={!shouldShowMenu}
                            onClose={removeBreakdown}
                            onClick={() => {
                                setFilterOpen(!filterOpen)
                            }}
                            popover={{
                                overlay: shouldShowMenu ? <Xx /> : undefined,
                                closeOnClickInside: false,
                                onVisibilityChange: (visible) => {
                                    setMenuOpen(visible)
                                },
                            }}
                            disablePropertyInfo={filterOpen || menuOpen}
                        />
                    </PopoverReferenceContext.Provider>
                </div>
            </TaxonomicBreakdownPopover>
        </BindLogic>
    )
}

type BreakdownTagProps = {
    breakdown: string | number
    breakdownType: BreakdownType | null | undefined
    disablePropertyInfo?: boolean
} & Omit<LemonTagProps, 'children'>

export function BreakdownTag({
    breakdown,
    breakdownType = 'event',
    disablePropertyInfo,
    ...props
}: BreakdownTagProps): JSX.Element {
    const { cohortsById } = useValues(cohortsModel)

    let propertyName = breakdown

    if (isAllCohort(breakdown)) {
        propertyName = 'All Users'
    } else if (isCohort(breakdown)) {
        propertyName = cohortsById[breakdown]?.name || `Cohort ${breakdown}`
    }

    return (
        <LemonTag className="breakdown-tag" {...props}>
            {breakdownType === 'hogql' ? (
                <HoqQLPropertyInfo value={propertyName as string} />
            ) : (
                <PropertyKeyInfo value={propertyName as string} disablePopover={disablePropertyInfo} />
            )}
        </LemonTag>
    )
}
