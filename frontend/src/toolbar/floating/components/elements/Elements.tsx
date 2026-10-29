import { useValues } from 'kea'

import { ElementInfoWindow } from '~/toolbar/floating/components/elements/ElementInfoWindow'
import { ElementOverlays } from '~/toolbar/shared/elements/ElementOverlays'
import { ElementHighlight } from '~/toolbar/shared/product-tours/ElementHighlight'
import { productToursLogic } from '~/toolbar/shared/product-tours/productToursLogic'

import { toolbarLogic } from '../../../shared/bar/toolbarLogic'

export function Elements(): JSX.Element {
    const { visibleMenu: activeToolbarMode } = useValues(toolbarLogic)
    const {
        isSelecting: productToursSelecting,
        hoverElementRect: productToursHoverRect,
        expandedStepRect: productToursSelectedStepRect,
    } = useValues(productToursLogic)

    const { theme } = useValues(toolbarLogic)

    // KLUDGE: if we put theme directly on the div then
    // linting and typescript complain about it not being
    // a valid attribute. So we put it in a variable and
    // spread it in. 🤷‍
    const themeProps = { theme }

    return (
        <>
            <div
                id="posthog-infowindow-container"
                className="w-full h-full absolute top-0 left-0 pointer-events-none z-[2147483021]"
                {...themeProps}
            >
                <ElementInfoWindow />
            </div>

            <ElementOverlays showHeatmapCanvas={activeToolbarMode === 'heatmap'}>
                {productToursSelecting && productToursHoverRect && <ElementHighlight rect={productToursHoverRect} />}
                {productToursSelectedStepRect && <ElementHighlight rect={productToursSelectedStepRect} isSelected />}
            </ElementOverlays>
        </>
    )
}
