import { IconEllipsis } from '@posthog/icons'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { useValues } from 'kea'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { userLogic } from 'scenes/userLogic'

import { PathsFilter } from '~/queries/schema'
import { AvailableFeature } from '~/types'

import { pathsDataLogicType } from './pathsDataLogicType'
import { pageUrl, PathNodeData } from './pathUtils'

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
    const { user } = useValues(userLogic)
    const hasAdvancedPaths = user?.organization?.available_features?.includes(AvailableFeature.PATHS_ADVANCED)

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
        void copyToClipboard(nodeName).then(captureException)
    }
    const openModal = (): void => openPersonsModal({ path_end_key: name })

    const isTruncatedPath = name.slice(1) === '_...'

    return (
        <div className="flex justify-between items-center w-full">
            <div className="font-semibold overflow-hidden max-h-16">
                <span className="text-xxs text-muted mr-1">{`0${name[0]}`}</span>
                <span className="text-xs break-words">{pageUrl(node, isPath)}</span>
            </div>
            <div className="flex flex-nowrap">
                <LemonButton size="small" onClick={openModal}>
                    <span className="text-link text-xs px-1 font-medium">{count}</span>
                </LemonButton>
                <LemonButtonWithDropdown
                    size="small"
                    icon={<IconEllipsis />}
                    disabledReason={
                        isTruncatedPath
                            ? 'Multiple paths truncated and combined for efficiency during querying. No further analysis possible.'
                            : undefined
                    }
                    dropdown={{
                        overlay: (
                            <>
                                <LemonButton size="small" fullWidth onClick={setAsPathStart}>
                                    Set as path start
                                </LemonButton>
                                {hasAdvancedPaths && (
                                    <>
                                        <LemonButton size="small" fullWidth onClick={setAsPathEnd}>
                                            Set as path end
                                        </LemonButton>
                                        <LemonButton size="small" fullWidth onClick={excludePathItem}>
                                            Exclude path item
                                        </LemonButton>
                                        <LemonButton size="small" fullWidth onClick={viewFunnel}>
                                            View funnel
                                        </LemonButton>
                                    </>
                                )}
                                <LemonButton size="small" fullWidth onClick={copyName}>
                                    Copy path item name
                                </LemonButton>
                            </>
                        ),
                        placement: 'bottom-end',
                    }}
                />
            </div>
        </div>
    )
}
