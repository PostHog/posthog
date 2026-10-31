import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { todayProductsLogic } from './todayProductsLogic'

export function TodayProductStarButton({
    product,
    starred,
}: {
    product: FileSystemImport
    starred: boolean
}): JSX.Element {
    const { shortcutDataLoading } = useValues(projectTreeDataLogic)
    const { toggleStarred } = useActions(todayProductsLogic)
    const label = starred ? 'Remove from starred' : 'Add to starred'
    return (
        <Tooltip>
            <TooltipTrigger
                delay={0}
                render={
                    <Button
                        size="icon-xs"
                        aria-label={label}
                        aria-pressed={starred}
                        disabled={shortcutDataLoading}
                        onClick={() => toggleStarred(product)}
                        data-attr={starred ? 'today-product-unstar' : 'today-product-star'}
                    />
                }
            >
                {starred ? <IconStarFilled /> : <IconStar />}
            </TooltipTrigger>
            <TooltipContent>{shortcutDataLoading ? 'Updating starred products' : label}</TooltipContent>
        </Tooltip>
    )
}
