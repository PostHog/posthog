import { useActions } from 'kea'

import { IconBookmark } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { GetSavedViewFiltersSummaryLines } from './SavedViewFiltersSummary'
import { SavedViewPayload, SavedViewsLogicProps, savedViewsLogic } from './savedViewsLogic'
import { SavedViewsModal } from './SavedViewsModal'

interface SavedViewsButtonProps {
    logicProps: SavedViewsLogicProps
    /** What the product saves with a view. The save dialog also summarizes `savePayload.filters`. */
    savePayload: SavedViewPayload
    getFiltersSummaryLines: GetSavedViewFiltersSummaryLines
    iconOnly?: boolean
    'data-attr'?: string
}

export function SavedViewsButton({
    logicProps,
    savePayload,
    getFiltersSummaryLines,
    iconOnly,
    'data-attr': dataAttr,
}: SavedViewsButtonProps): JSX.Element {
    const { openModal } = useActions(savedViewsLogic(logicProps))

    return (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconBookmark />}
                onClick={openModal}
                tooltip={iconOnly ? 'Saved views' : undefined}
                data-attr={dataAttr}
            >
                {iconOnly ? undefined : 'Saved views'}
            </LemonButton>
            <SavedViewsModal
                logicProps={logicProps}
                savePayload={savePayload}
                getFiltersSummaryLines={getFiltersSummaryLines}
            />
        </>
    )
}
