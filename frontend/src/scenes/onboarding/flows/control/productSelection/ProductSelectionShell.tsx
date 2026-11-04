import { OnboardingExitModal } from '../exit/index'
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
