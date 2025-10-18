import { useValues } from 'kea'
import posthog from 'posthog-js'

import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonMenu, PopoverReferenceContext } from '@posthog/lemon-ui'

import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { PathsFilter } from '~/queries/schema/schema-general'
import { AvailableFeature } from '~/types'

import { PathNodeData, pageUrl } from './pathUtils'
import { pathsDataLogicType } from './pathsDataLogicType'

type PathNodeCardButton = {
    name: string
    count: number
    node: PathNodeData
    viewPathToFunnel: pathsDataLogicType['actions']['viewPathToFunnel']
    openPersonsModal: pathsDataLogicType['actions']['openPersonsModal']
    filter: PathsFilter
    setFilter: (filter: PathsFilter) => void
}

export function PathNodeCardButton({
    name,
    count,
    node,
    viewPathToFunnel,
    openPersonsModal,
    filter,
    setFilter,
}: PathNodeCardButton): JSX.Element {
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)

    const nodeName = pageUrl(node)
    const isPath = nodeName.includes('/')

    const setAsPathStart = (): void => setFilter({ startPoint: nodeName })
    const setAsPathEnd = (): void => setFilter({ endPoint: nodeName })
    const excludePathItem = (): void => {
        setFilter({ excludeEvents: [...(filter.excludeEvents || []), pageUrl(node, false)] })
    }
    const viewFunnel = (): void => {
        viewPathToFunnel(node)
    }
    const copyName = (): void => {
        void copyToClipboard(nodeName).catch((e) => posthog.captureException(e))
    }
    const openModal = (): void => openPersonsModal({ path_end_key: name })

    const isTruncatedPath = name.slice(1) === '_...'

    return (
        <div className="flex justify-between items-center w-full">
            <div className="font-semibold overflow-hidden max-h-16">
                <span className="text-xxs text-secondary mr-1">{`0${name[0]}`}</span>
                <span className="text-xs break-words">{pageUrl(node, isPath)}</span>
            </div>
            {/* TRICKY: We don't want the popover to affect the buttons */}
            <PopoverReferenceContext.Provider value={null}>
                <div className="flex flex-nowrap">
                    <LemonButton size="small" onClick={openModal}>
                        <span className="text-link text-xs px-1 font-medium">{count}</span>
                    </LemonButton>
                    <LemonMenu
                        items={[
                            { label: 'Set as path start', onClick: setAsPathStart },
                            ...(hasAdvancedPaths
                                ? [
                                      { label: 'Set as path end', onClick: setAsPathEnd },
                                      { label: 'Exclude path item', onClick: excludePathItem },
                                      {
                                          label: (
                                              <div className="flex justify-between items-center w-full">
                                                  <span>View funnel</span>
                                                  <IconOpenInNew />
                                              </div>
                                          ),
                                          onClick: viewFunnel,
                                      },
                                  ]
                                : []),
                            { label: 'Copy path item name', onClick: copyName },
                        ]}
                        placement="bottom-end"
                    >
                        <LemonButton
                            size="small"
                            icon={<IconEllipsis />}
                            disabledReason={
                                isTruncatedPath
                                    ? 'Multiple paths truncated and combined for efficiency during querying. No further analysis possible.'
                                    : undefined
                            }
                        />
                    </LemonMenu>
                </div>
            </PopoverReferenceContext.Provider>
        </div>
    )
}
