import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { navProductsTabLogic } from './navProductsTabLogic'
import { productsItemName } from './productsCatalog'

export function ConfigureStarredModal(): JSX.Element {
    const { configureStarredOpen, configurableProducts, starredProductIds } = useValues(navProductsTabLogic)
    const { setConfigureStarredOpen, setProductStarred } = useActions(navProductsTabLogic)
    const { shortcutDataHasLoaded, shortcutDataLoading } = useValues(projectTreeDataLogic)

    return (
        <LemonModal
            title="Configure starred"
            description="Choose which products appear in Starred. Changes save automatically."
            isOpen={configureStarredOpen}
            onClose={() => setConfigureStarredOpen(false)}
            width={640}
            footer={
                <div className="flex items-center gap-4 w-full">
                    <p className="text-xs text-secondary mb-0 flex-1">
                        Tip: Drag starred items in the sidebar to rearrange them.
                    </p>
                    <LemonButton type="primary" onClick={() => setConfigureStarredOpen(false)}>
                        Done
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-2 group/colorful-product-icons colorful-product-icons-true">
                {!shortcutDataHasLoaded ? (
                    <Spinner />
                ) : (
                    configurableProducts.map((item) => {
                        const { description, docsHref } = sidebarProductMeta(item)
                        const label = productsItemName(item)
                        return (
                            <LemonSwitch
                                key={item.path}
                                className="py-2"
                                checked={!!starredProductIds[item.path]}
                                onChange={(starred) => setProductStarred(item.path, starred)}
                                loading={shortcutDataLoading}
                                aria-label={label}
                                bordered
                                fullWidth
                                label={
                                    <span className="flex items-center gap-2">
                                        <span className="text-lg shrink-0 flex items-center">
                                            {iconForType(item.iconType, item.iconColor)}
                                        </span>
                                        <span className="flex flex-col">
                                            <span className="flex items-center gap-2">
                                                {label}
                                                {docsHref && (
                                                    <Link
                                                        to={docsHref}
                                                        target="_blank"
                                                        className="text-xs font-normal"
                                                        onClick={(event) => event.stopPropagation()}
                                                    >
                                                        Docs
                                                    </Link>
                                                )}
                                            </span>
                                            {description && (
                                                <span className="text-xs font-normal text-secondary">
                                                    {description}
                                                </span>
                                            )}
                                        </span>
                                    </span>
                                }
                            />
                        )
                    })
                )}
            </div>
        </LemonModal>
    )
}
