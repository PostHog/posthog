import { commandExamples } from 'lib/components/Search/commandDescriptions'

import { FileSystemImport } from '~/queries/schema/schema-general'

import { sidebarProductMeta } from '../../sidebarProductMeta'
import { productsItemName } from './productsCatalog'

export function NavProductTooltip({ item }: { item: FileSystemImport }): JSX.Element {
    const isGroup = item.iconType === 'group' || item.iconType?.startsWith('group_') || item.type?.startsWith('group_')
    const description = sidebarProductMeta(item).description
    const example = isGroup ? undefined : commandExamples[item.path]
    return (
        <div className="w-72 max-w-full p-1 text-left whitespace-normal">
            <div className="text-sm font-semibold mb-2">{productsItemName(item)}</div>
            <div className="text-xs leading-relaxed">
                {description ??
                    (isGroup
                        ? 'Explore the organizations, accounts, or other groups behind your events. Understand usage at the group level.'
                        : `Explore ${productsItemName(item).toLowerCase()} in your project.`)}
            </div>
            {(example || isGroup) && (
                <div className="mt-3 border-t border-current/20 pt-2">
                    <div className="text-xs font-semibold mb-1">For example</div>
                    <div className="text-xs leading-relaxed text-secondary">
                        {example ?? 'Compare activity across customer accounts.'}
                    </div>
                </div>
            )}
        </div>
    )
}
