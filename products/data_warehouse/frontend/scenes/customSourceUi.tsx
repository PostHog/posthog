import { ComponentType } from 'react'

import { ExternalDataSourceType } from '~/queries/schema/schema-general'

import { ExcelSourceForm } from './NewSourceScene/components/ExcelSourceForm'
import { FileUploadSourceForm } from './NewSourceScene/components/FileUploadSourceForm'
import { EXCEL_SOURCE_NAME } from './NewSourceScene/excelSourceLogic'
import { FILE_UPLOAD_SOURCE_NAME } from './NewSourceScene/fileUploadSource'
import { type SourceWizardLogicProps } from './NewSourceScene/sourceWizardLogic'
import { ExcelConfigurationForm } from './SourceScene/tabs/ExcelConfigurationForm'

/** Props every custom wizard form receives; a form that doesn't need them can ignore them. */
export interface CustomSourceWizardFormProps {
    sourceWizardLogicProps?: SourceWizardLogicProps
}

interface CustomSourceUi {
    /** Replaces the generic connection form on the wizard's second step. */
    WizardForm: ComponentType<CustomSourceWizardFormProps>
    /** The form drives its own submit — the wizard footer's Next would submit the generic
     * connection form this source never renders. */
    hidesWizardFooter?: boolean
    /** Replaces the generic form on the source's Configuration tab. */
    ConfigurationForm?: ComponentType
}

// The one place a source registers bespoke UI. The wizard and configuration scenes dispatch
// through this instead of naming sources — the frontend counterpart of the backend rule that
// generic layers stay source-agnostic.
const CUSTOM_SOURCE_UI: Partial<Record<ExternalDataSourceType, CustomSourceUi>> = {
    [FILE_UPLOAD_SOURCE_NAME]: {
        WizardForm: FileUploadSourceForm,
        hidesWizardFooter: true,
    },
    [EXCEL_SOURCE_NAME]: {
        WizardForm: ExcelSourceForm,
        ConfigurationForm: ExcelConfigurationForm,
    },
}

export function getCustomSourceUi(
    sourceType: ExternalDataSourceType | string | null | undefined
): CustomSourceUi | null {
    if (!sourceType) {
        return null
    }
    return CUSTOM_SOURCE_UI[sourceType as ExternalDataSourceType] ?? null
}
