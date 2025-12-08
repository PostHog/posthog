import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'

import { productToursLogic } from './productToursLogic'

export function ProductToursToolbarMenu(): JSX.Element {
    const { newTour } = useActions(productToursLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <span>Product tours</span>
            </ToolbarMenu.Header>
            <ToolbarMenu.Body>
                <div className="p-2 space-y-2">
                    <p className="text-muted text-sm">Create product tours to guide users through your application.</p>
                    {/* TODO: list existing tours */}
                    <LemonButton type="primary" fullWidth onClick={() => newTour()}>
                        Create new tour
                    </LemonButton>
                </div>
            </ToolbarMenu.Body>
        </ToolbarMenu>
    )
}
