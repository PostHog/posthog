export enum SQLEditorMode {
    FullScene = 'full_scene',
    BusinessIntelligence = 'business_intelligence',
    Embedded = 'embedded',
}

export const isEmbeddedSQLEditorMode = (mode: SQLEditorMode): boolean => mode === SQLEditorMode.Embedded
