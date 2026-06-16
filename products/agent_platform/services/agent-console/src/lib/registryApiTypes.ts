/*
 * Stub types for the agent custom-tool / skill template registry.
 *
 * The registry backend (`AgentCustomToolTemplateViewSet` / `AgentSkillTemplateViewSet`)
 * is disabled "pending a rethink", so these `*Api` types are no longer emitted into
 * `@/generated/agent-platform.api.schemas` and the (currently unused) console registry
 * feature fails to compile. Stub them here so the console builds. Re-point these imports
 * back at the generated schema when the registry backend is re-enabled.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
export type CustomToolTemplateCreateApi = any
export type CustomToolTemplateDetailApi = any
export type CustomToolTemplateDuplicateApi = any
export type CustomToolTemplatePublishApi = any
export type CustomToolTemplateSummaryApi = any
export type CustomToolTemplateUsageApi = any
export type SkillTemplateCreateApi = any
export type SkillTemplateDetailApi = any
export type SkillTemplateDuplicateApi = any
export type SkillTemplateFileApi = any
export type SkillTemplateFileRenameApi = any
export type SkillTemplateFileWriteApi = any
export type SkillTemplatePublishApi = any
export type SkillTemplateSummaryApi = any
export type SkillTemplateUsageApi = any
export type TemplateVersionEntryApi = any
