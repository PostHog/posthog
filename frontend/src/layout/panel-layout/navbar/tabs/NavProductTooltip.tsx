import { FileSystemImport } from '~/queries/schema/schema-general'

import { sidebarProductMeta } from '../../sidebarProductMeta'
import { productsItemName } from './productsCatalog'

export function NavProductTooltip({ item }: { item: FileSystemImport }): JSX.Element {
    const { description, example } = sidebarProductMeta(item)
    return (
        <div className="w-72 max-w-full p-1 text-left whitespace-normal">
            <div className="text-sm font-semibold mb-2">{productsItemName(item)}</div>
            <div className="text-xs leading-relaxed">
                {description ?? `Explore ${productsItemName(item).toLowerCase()} in your project.`}
            </div>
            {example && (
                <div className="mt-3 border-t border-current/20 pt-2">
                    <div className="text-xs font-semibold mb-1">For example</div>
                    <div className="text-xs leading-relaxed text-secondary">{example}</div>
                </div>
            )}
        </div>
    )
}
