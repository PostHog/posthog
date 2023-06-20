import { useValues } from 'kea'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { EditorFilterProps } from '~/types'

export function TrendsFormulaLabel({ insightProps }: EditorFilterProps): JSX.Element | null {
    const { hasFormula } = useValues(insightVizDataLogic(insightProps))
    return hasFormula ? <>Formula</> : null
}
