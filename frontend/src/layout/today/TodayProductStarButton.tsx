import { useActions, useValues } from 'kea'

import { IconStar, IconStarFilled } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { findProductShortcut } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'

import { todayToolsLogic } from './todayToolsLogic'

/** Stars a product, or removes its star. The stars are the same as in the current navigation. */
export function TodayProductStarButton({ product }: { product: FileSystemImport }): JSX.Element {
    const { shortcutData, shortcutDataLoading } = useValues(projectTreeDataLogic)
    const { toggleStarred } = useActions(todayToolsLogic)
    const starred = !!findProductShortcut(product, shortcutData)
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
