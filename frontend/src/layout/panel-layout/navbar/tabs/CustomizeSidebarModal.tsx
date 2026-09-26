import { useActions, useValues } from 'kea'

import { LemonButton, LemonLabel, LemonModal, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'

import { HomepageConfiguration } from '~/layout/scenes/HomepageConfiguration'

import { iconForType } from '../../ProjectTree/defaultTree'
import { projectTreeDataLogic } from '../../ProjectTree/projectTreeDataLogic'
import { sidebarProductMeta } from '../../sidebarProductMeta'
import { navProductsTabLogic } from './navProductsTabLogic'
import { productsItemName } from './productsCatalog'

export function CustomizeSidebarModal(): JSX.Element {
    const { customizeSidebarOpen, configurableProducts, starredProductIds } = useValues(navProductsTabLogic)
    const { setCustomizeSidebarOpen, setProductStarred } = useActions(navProductsTabLogic)
    const { shortcutDataHasLoaded, shortcutDataLoading } = useValues(projectTreeDataLogic)

    return (
        <LemonModal
            title="Customize sidebar"
            description="Changes save automatically."
            isOpen={customizeSidebarOpen}
            onClose={() => setCustomizeSidebarOpen(false)}
            width={640}
            footer={
                <div className="flex items-center gap-4 w-full">
                    <p className="text-xs text-secondary mb-0 flex-1">
                        Tip: Drag starred items in the sidebar to rearrange them.
                    </p>
                    <LemonButton type="primary" onClick={() => setCustomizeSidebarOpen(false)}>
                        Done
                    </LemonButton>
                </div>
            }
        >
            <div className="flex flex-col gap-6">
                <section className="flex flex-col gap-2">
                    <div>
                        <LemonLabel>Homepage</LemonLabel>
                        <p className="text-xs text-secondary mb-0">The page that opens when you select Home.</p>
                    </div>
                    <HomepageConfiguration />
                </section>
                <section className="flex flex-col gap-2 group/colorful-product-icons colorful-product-icons-true">
                    <div>
                        <LemonLabel>Starred</LemonLabel>
                        <p className="text-xs text-secondary mb-0">
                            Starred products appear below Home in the sidebar.
                        </p>
                    </div>
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
                </section>
            </div>
        </LemonModal>
    )
}
