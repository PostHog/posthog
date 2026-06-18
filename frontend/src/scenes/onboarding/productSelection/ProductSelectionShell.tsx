import { OnboardingExitModal } from '../exit'
import { ProductSelection } from './ProductSelection'

export function ProductSelectionShell(): JSX.Element {
    return (
        <>
            <ProductSelection />
            <OnboardingExitModal />
        </>
    )
}

export default ProductSelectionShell
