import { useValues } from 'kea'

import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, PathsFilterType } from '~/types'
import { LemonButton, LemonButtonWithDropdown } from '@posthog/lemon-ui'
import { IconEllipsis } from 'lib/lemon-ui/icons'
import { copyToClipboard } from 'lib/utils'

import { pageUrl, PathNodeData } from './pathUtils'
import { pathsDataLogicType } from './pathsDataLogicType'
import { captureException } from '@sentry/react'

type PathNodeCardButton = {
    name: string
    count: number
    node: PathNodeData
    viewPathToFunnel: pathsDataLogicType['actions']['viewPathToFunnel']
    openPersonsModal: pathsDataLogicType['actions']['openPersonsModal']
    filter: PathsFilterType
    setFilter: (filter: PathsFilterType) => void
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

    const setAsPathStart = (): void => setFilter({ start_point: pageUrl(node) })
    const setAsPathEnd = (): void => setFilter({ end_point: pageUrl(node) })
    const excludePathItem = (): void => {
        setFilter({ exclude_events: [...(filter.exclude_events || []), pageUrl(node, false)] })
    }
    const viewFunnel = (): void => {
        viewPathToFunnel(node)
    }
    const copyName = (): void => {
        void copyToClipboard(pageUrl(node)).then(captureException)
    }
    const openModal = (): void => openPersonsModal({ path_end_key: name })

    return (
        <div className="flex justify-between items-center w-full">
            <div className="flex items-center font-semibold">
                <span className="text-xxs text-muted mr-1">{`0${name[0]}`}</span>
                <span className="text-xs">{pageUrl(node, true)}</span>
            </div>
            <div className="flex flex-nowrap">
                <LemonButton size="small" status="stealth">
                    <span className="text-link text-xs pr-1 font-medium" onClick={openModal}>
                        {count}
                    </span>
                </LemonButton>
                <LemonButtonWithDropdown
                    size="small"
                    status="muted"
                    icon={<IconEllipsis />}
                    dropdown={{
                        overlay: (
                            <>
                                <LemonButton size="small" fullWidth status="stealth" onClick={setAsPathStart}>
                                    Set as path start
                                </LemonButton>
                                {hasAdvancedPaths && (
                                    <>
                                        <LemonButton size="small" fullWidth status="stealth" onClick={setAsPathEnd}>
                                            Set as path end
                                        </LemonButton>
                                        <LemonButton size="small" fullWidth status="stealth" onClick={excludePathItem}>
                                            Exclude path item
                                        </LemonButton>
                                        <LemonButton size="small" fullWidth status="stealth" onClick={viewFunnel}>
                                            View funnel
                                        </LemonButton>
                                    </>
                                )}
                                <LemonButton size="small" fullWidth status="stealth" onClick={copyName}>
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
