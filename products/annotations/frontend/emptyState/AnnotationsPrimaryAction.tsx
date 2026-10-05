import { useActions } from 'kea'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { annotationModalHostLogic } from '../logics/annotationModalHostLogic'

export function AnnotationsPrimaryAction(): JSX.Element {
    const { openModalToCreateAnnotation } = useActions(annotationModalHostLogic)

    return (
        <LemonButton type="primary" onClick={() => openModalToCreateAnnotation()} data-attr="create-annotation">
            Create your first annotation
        </LemonButton>
    )
}
