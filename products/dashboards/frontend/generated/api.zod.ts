/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const dashboardsCollaboratorsListResponseUserOneDistinctIdMax = 200

export const dashboardsCollaboratorsListResponseUserOneFirstNameMax = 150

export const dashboardsCollaboratorsListResponseUserOneLastNameMax = 150

export const dashboardsCollaboratorsListResponseUserOneEmailMax = 254

export const DashboardsCollaboratorsListResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    dashboard_id: zod.number(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dashboardsCollaboratorsListResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dashboardsCollaboratorsListResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(dashboardsCollaboratorsListResponseUserOneLastNameMax).optional(),
        email: zod.email().max(dashboardsCollaboratorsListResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    added_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    user_uuid: zod.uuid(),
})
export const DashboardsCollaboratorsListResponse = /* @__PURE__ */ zod.array(DashboardsCollaboratorsListResponseItem)

export const DashboardsCollaboratorsCreateBody = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    user_uuid: zod.uuid(),
})

export const dashboardTemplatesListResponseResultsItemTemplateNameMax = 400

export const dashboardTemplatesListResponseResultsItemDashboardDescriptionMax = 400

export const dashboardTemplatesListResponseResultsItemTagsItemMax = 255

export const dashboardTemplatesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const dashboardTemplatesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const dashboardTemplatesListResponseResultsItemCreatedByOneLastNameMax = 150

export const dashboardTemplatesListResponseResultsItemCreatedByOneEmailMax = 254

export const dashboardTemplatesListResponseResultsItemImageUrlMax = 8201

export const dashboardTemplatesListResponseResultsItemAvailabilityContextsItemMax = 255

export const DashboardTemplatesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.uuid(),
            template_name: zod.string().max(dashboardTemplatesListResponseResultsItemTemplateNameMax).nullish(),
            dashboard_description: zod
                .string()
                .max(dashboardTemplatesListResponseResultsItemDashboardDescriptionMax)
                .nullish(),
            dashboard_filters: zod.unknown().nullish(),
            tags: zod.array(zod.string().max(dashboardTemplatesListResponseResultsItemTagsItemMax)).nullish(),
            tiles: zod.unknown().nullish(),
            variables: zod.unknown().nullish(),
            deleted: zod.boolean().nullish(),
            created_at: zod.iso.datetime({}).nullable(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(dashboardTemplatesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod
                    .string()
                    .max(dashboardTemplatesListResponseResultsItemCreatedByOneFirstNameMax)
                    .optional(),
                last_name: zod
                    .string()
                    .max(dashboardTemplatesListResponseResultsItemCreatedByOneLastNameMax)
                    .optional(),
                email: zod.email().max(dashboardTemplatesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
            image_url: zod.string().max(dashboardTemplatesListResponseResultsItemImageUrlMax).nullish(),
            team_id: zod.number().nullable(),
            scope: zod
                .union([
                    zod
                        .enum(['team', 'global', 'feature_flag'])
                        .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
            availability_contexts: zod
                .array(zod.string().max(dashboardTemplatesListResponseResultsItemAvailabilityContextsItemMax))
                .nullish(),
            is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
        })
    ),
})

export const dashboardTemplatesCreateBodyTemplateNameMax = 400

export const dashboardTemplatesCreateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesCreateBodyTagsItemMax = 255

export const dashboardTemplatesCreateBodyImageUrlMax = 8201

export const dashboardTemplatesCreateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesCreateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesCreateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesCreateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesCreateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesCreateBodyImageUrlMax).nullish(),
    scope: zod
        .union([
            zod
                .enum(['team', 'global', 'feature_flag'])
                .describe('* `team` - Only team\n* `global` - Global\n* `feature_flag` - Feature Flag'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    availability_contexts: zod
        .array(zod.string().max(dashboardTemplatesCreateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardsListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const dashboardsListResponseResultsItemCreatedByOneFirstNameMax = 150

export const dashboardsListResponseResultsItemCreatedByOneLastNameMax = 150

export const dashboardsListResponseResultsItemCreatedByOneEmailMax = 254

export const DashboardsListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod
            .object({
                id: zod.number(),
                name: zod.string().nullable().describe('Name of the dashboard.'),
                description: zod.string().describe('Description of the dashboard.'),
                pinned: zod.boolean().describe('Whether the dashboard is pinned to the top of the list.'),
                created_at: zod.iso.datetime({}),
                created_by: zod.object({
                    id: zod.number(),
                    uuid: zod.uuid(),
                    distinct_id: zod.string().max(dashboardsListResponseResultsItemCreatedByOneDistinctIdMax).nullish(),
                    first_name: zod.string().max(dashboardsListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                    last_name: zod.string().max(dashboardsListResponseResultsItemCreatedByOneLastNameMax).optional(),
                    email: zod.email().max(dashboardsListResponseResultsItemCreatedByOneEmailMax),
                    is_email_verified: zod.boolean().nullish(),
                    hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                    role_at_organization: zod
                        .union([
                            zod
                                .enum([
                                    'engineering',
                                    'data',
                                    'product',
                                    'founder',
                                    'leadership',
                                    'marketing',
                                    'sales',
                                    'other',
                                ])
                                .describe(
                                    '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                                ),
                            zod.enum(['']),
                            zod.literal(null),
                        ])
                        .nullish(),
                }),
                last_accessed_at: zod.iso.datetime({}).nullable(),
                last_viewed_at: zod.iso.datetime({}).nullable(),
                is_shared: zod.boolean(),
                deleted: zod.boolean(),
                creation_mode: zod
                    .enum(['default', 'template', 'duplicate', 'unlisted'])
                    .describe(
                        '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
                    ),
                tags: zod.array(zod.unknown()).optional(),
                restriction_level: zod
                    .union([zod.literal(21), zod.literal(37)])
                    .describe(
                        '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
                    )
                    .describe(
                        'Controls who can edit the dashboard.\n\n* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
                    ),
                effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
                effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
                user_access_level: zod
                    .string()
                    .nullable()
                    .describe('The effective access level the user has for this object'),
                access_control_version: zod.string(),
                last_refresh: zod.iso.datetime({}).nullable(),
                team_id: zod.number(),
            })
            .describe('Serializer mixin that handles tags for objects.')
    ),
})

export const dashboardsCreateBodyNameMax = 400

export const dashboardsCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsCollaboratorsList2ResponseUserOneDistinctIdMax = 200

export const dashboardsCollaboratorsList2ResponseUserOneFirstNameMax = 150

export const dashboardsCollaboratorsList2ResponseUserOneLastNameMax = 150

export const dashboardsCollaboratorsList2ResponseUserOneEmailMax = 254

export const DashboardsCollaboratorsList2ResponseItem = /* @__PURE__ */ zod.object({
    id: zod.uuid(),
    dashboard_id: zod.number(),
    user: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dashboardsCollaboratorsList2ResponseUserOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dashboardsCollaboratorsList2ResponseUserOneFirstNameMax).optional(),
        last_name: zod.string().max(dashboardsCollaboratorsList2ResponseUserOneLastNameMax).optional(),
        email: zod.email().max(dashboardsCollaboratorsList2ResponseUserOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    added_at: zod.iso.datetime({}),
    updated_at: zod.iso.datetime({}),
    user_uuid: zod.uuid(),
})
export const DashboardsCollaboratorsList2Response = /* @__PURE__ */ zod.array(DashboardsCollaboratorsList2ResponseItem)

export const DashboardsCollaboratorsCreate2Body = /* @__PURE__ */ zod.object({
    level: zod
        .union([zod.literal(21), zod.literal(37)])
        .describe('* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'),
    user_uuid: zod.uuid(),
})

export const dashboardsSharingListResponseSharePasswordsItemNoteMax = 100

export const DashboardsSharingListResponseItem = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(dashboardsSharingListResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})
export const DashboardsSharingListResponse = /* @__PURE__ */ zod.array(DashboardsSharingListResponseItem)

/**
 * Create a new password for the sharing configuration.
 */
export const DashboardsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const dashboardsSharingPasswordsCreateResponseSharePasswordsItemNoteMax = 100

export const DashboardsSharingPasswordsCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(dashboardsSharingPasswordsCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const DashboardsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const dashboardsSharingRefreshCreateResponseSharePasswordsItemNoteMax = 100

export const DashboardsSharingRefreshCreateResponse = /* @__PURE__ */ zod.object({
    created_at: zod.iso.datetime({}),
    enabled: zod.boolean().optional(),
    access_token: zod.string().nullable(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
    share_passwords: zod.array(
        zod.object({
            id: zod.number(),
            created_at: zod.iso.datetime({}),
            note: zod.string().max(dashboardsSharingRefreshCreateResponseSharePasswordsItemNoteMax).nullish(),
            created_by_email: zod.string(),
            is_active: zod.boolean(),
        })
    ),
})

export const dashboardsRetrieveResponseNameMax = 400

export const dashboardsRetrieveResponseCreatedByOneDistinctIdMax = 200

export const dashboardsRetrieveResponseCreatedByOneFirstNameMax = 150

export const dashboardsRetrieveResponseCreatedByOneLastNameMax = 150

export const dashboardsRetrieveResponseCreatedByOneEmailMax = 254

export const dashboardsRetrieveResponseDeleteInsightsDefault = false

export const DashboardsRetrieveResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardsRetrieveResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(dashboardsRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsRetrieveResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsRetrieveResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(dashboardsRetrieveResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        last_viewed_at: zod.iso.datetime({}).nullable(),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: zod
            .enum(['default', 'template', 'duplicate', 'unlisted'])
            .describe(
                '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
            ),
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
        effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({}).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsRetrieveResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsUpdateBodyNameMax = 400

export const dashboardsUpdateBodyDeleteInsightsDefault = false

export const DashboardsUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsUpdateResponseNameMax = 400

export const dashboardsUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardsUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardsUpdateResponseCreatedByOneEmailMax = 254

export const dashboardsUpdateResponseDeleteInsightsDefault = false

export const DashboardsUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardsUpdateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(dashboardsUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(dashboardsUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        last_viewed_at: zod.iso.datetime({}).nullable(),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: zod
            .enum(['default', 'template', 'duplicate', 'unlisted'])
            .describe(
                '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
            ),
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
        effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({}).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsUpdateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsPartialUpdateBodyNameMax = 400

export const dashboardsPartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsPartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsPartialUpdateResponseNameMax = 400

export const dashboardsPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const dashboardsPartialUpdateResponseCreatedByOneLastNameMax = 150

export const dashboardsPartialUpdateResponseCreatedByOneEmailMax = 254

export const dashboardsPartialUpdateResponseDeleteInsightsDefault = false

export const DashboardsPartialUpdateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardsPartialUpdateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsPartialUpdateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(dashboardsPartialUpdateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        last_viewed_at: zod.iso.datetime({}).nullable(),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: zod
            .enum(['default', 'template', 'duplicate', 'unlisted'])
            .describe(
                '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
            ),
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
        effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({}).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsPartialUpdateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Generate AI analysis comparing before/after dashboard refresh.
Expects cache_key in request body pointing to the stored 'before' state.
 */
export const dashboardsAnalyzeRefreshResultCreateBodyNameMax = 400

export const dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault = false

export const DashboardsAnalyzeRefreshResultCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsAnalyzeRefreshResultCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsAnalyzeRefreshResultCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Copy an existing dashboard tile to another dashboard (insight or text card; new tile row).
 */
export const DashboardsCopyTileCreateBody = /* @__PURE__ */ zod.object({
    fromDashboardId: zod.number().describe('Dashboard id the tile currently belongs to.'),
    tileId: zod.number().describe('Dashboard tile id to copy.'),
})

export const dashboardsCopyTileCreateResponseNameMax = 400

export const dashboardsCopyTileCreateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsCopyTileCreateResponseCreatedByOneFirstNameMax = 150

export const dashboardsCopyTileCreateResponseCreatedByOneLastNameMax = 150

export const dashboardsCopyTileCreateResponseCreatedByOneEmailMax = 254

export const dashboardsCopyTileCreateResponseDeleteInsightsDefault = false

export const DashboardsCopyTileCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardsCopyTileCreateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(dashboardsCopyTileCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsCopyTileCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsCopyTileCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(dashboardsCopyTileCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        last_viewed_at: zod.iso.datetime({}).nullable(),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: zod
            .enum(['default', 'template', 'duplicate', 'unlisted'])
            .describe(
                '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
            ),
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
        effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({}).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCopyTileCreateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Generate an AI-suggested name and description from this dashboard's tiles.
 */
export const DashboardsGenerateMetadataCreateResponse = /* @__PURE__ */ zod.object({
    name: zod.string(),
    description: zod.string(),
})

export const dashboardsMoveTilePartialUpdateBodyNameMax = 400

export const dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault = false

export const DashboardsMoveTilePartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsMoveTilePartialUpdateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsMoveTilePartialUpdateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const DashboardsReorderTilesCreateBody = /* @__PURE__ */ zod.object({
    tile_order: zod
        .array(zod.number())
        .min(1)
        .describe('Array of tile IDs in the desired display order (top to bottom, left to right).'),
})

export const dashboardsReorderTilesCreateResponseNameMax = 400

export const dashboardsReorderTilesCreateResponseCreatedByOneDistinctIdMax = 200

export const dashboardsReorderTilesCreateResponseCreatedByOneFirstNameMax = 150

export const dashboardsReorderTilesCreateResponseCreatedByOneLastNameMax = 150

export const dashboardsReorderTilesCreateResponseCreatedByOneEmailMax = 254

export const dashboardsReorderTilesCreateResponseDeleteInsightsDefault = false

export const DashboardsReorderTilesCreateResponse = /* @__PURE__ */ zod
    .object({
        id: zod.number(),
        name: zod.string().max(dashboardsReorderTilesCreateResponseNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        created_at: zod.iso.datetime({}),
        created_by: zod.object({
            id: zod.number(),
            uuid: zod.uuid(),
            distinct_id: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneDistinctIdMax).nullish(),
            first_name: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneFirstNameMax).optional(),
            last_name: zod.string().max(dashboardsReorderTilesCreateResponseCreatedByOneLastNameMax).optional(),
            email: zod.email().max(dashboardsReorderTilesCreateResponseCreatedByOneEmailMax),
            is_email_verified: zod.boolean().nullish(),
            hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
            role_at_organization: zod
                .union([
                    zod
                        .enum([
                            'engineering',
                            'data',
                            'product',
                            'founder',
                            'leadership',
                            'marketing',
                            'sales',
                            'other',
                        ])
                        .describe(
                            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                        ),
                    zod.enum(['']),
                    zod.literal(null),
                ])
                .nullish(),
        }),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        last_viewed_at: zod.iso.datetime({}).nullable(),
        is_shared: zod.boolean(),
        deleted: zod.boolean().optional(),
        creation_mode: zod
            .enum(['default', 'template', 'duplicate', 'unlisted'])
            .describe(
                '* `default` - Default\n* `template` - Template\n* `duplicate` - Duplicate\n* `unlisted` - Unlisted (product-embedded)'
            ),
        filters: zod.record(zod.string(), zod.unknown()),
        variables: zod.record(zod.string(), zod.unknown()).nullable(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        effective_restriction_level: zod.union([zod.literal(21), zod.literal(37)]),
        effective_privilege_level: zod.union([zod.literal(21), zod.literal(37)]),
        user_access_level: zod.string().nullable().describe('The effective access level the user has for this object'),
        access_control_version: zod.string(),
        last_refresh: zod.iso.datetime({}).nullish(),
        persisted_filters: zod.record(zod.string(), zod.unknown()).nullable(),
        persisted_variables: zod.record(zod.string(), zod.unknown()).nullable(),
        team_id: zod.number(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        tiles: zod.array(zod.record(zod.string(), zod.unknown())).nullable(),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsReorderTilesCreateResponseDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Run all insights on a dashboard and return their results.
 */
export const DashboardsRunInsightsRetrieveResponse = /* @__PURE__ */ zod.object({
    results: zod
        .array(
            zod
                .object({
                    id: zod.number().optional(),
                    insight: zod
                        .object({
                            id: zod.number(),
                            short_id: zod.string(),
                            name: zod.string().nullable(),
                            derived_name: zod.string().nullable(),
                            result: zod.unknown(),
                        })
                        .describe('InsightSerializer restricted to identifiers + result only.'),
                })
                .describe('DashboardTileSerializer restricted to tile id + insight result fields.')
        )
        .describe('Results for each insight tile on the dashboard.'),
})

/**
 * Snapshot the current dashboard state (from cache) for AI analysis.
Returns a cache_key representing the 'before' state, to be used with analyze_refresh_result.
 */
export const dashboardsSnapshotCreateBodyNameMax = 400

export const dashboardsSnapshotCreateBodyDeleteInsightsDefault = false

export const DashboardsSnapshotCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsSnapshotCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsSnapshotCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dashboardsCreateFromTemplateJsonCreateBodyNameMax = 400

export const dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateFromTemplateJsonCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateFromTemplateJsonCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateFromTemplateJsonCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Creates an unlisted dashboard from template by tag.
Enforces uniqueness (one per tag per team).
Returns 409 if unlisted dashboard with this tag already exists.
 */
export const dashboardsCreateUnlistedDashboardCreateBodyNameMax = 400

export const dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault = false

export const DashboardsCreateUnlistedDashboardCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod.string().max(dashboardsCreateUnlistedDashboardCreateBodyNameMax).nullish(),
        description: zod.string().optional(),
        pinned: zod.boolean().optional(),
        last_accessed_at: zod.iso.datetime({}).nullish(),
        deleted: zod.boolean().optional(),
        breakdown_colors: zod.unknown().optional().describe('Custom color mapping for breakdown values.'),
        data_color_theme_id: zod.number().nullish().describe('ID of the color theme used for chart visualizations.'),
        tags: zod.array(zod.unknown()).optional(),
        restriction_level: zod
            .union([zod.literal(21), zod.literal(37)])
            .describe(
                '* `21` - Everyone in the project can edit\n* `37` - Only those invited to this dashboard can edit'
            )
            .optional(),
        last_refresh: zod.iso.datetime({}).nullish(),
        quick_filter_ids: zod
            .array(zod.string())
            .nullish()
            .describe('List of quick filter IDs associated with this dashboard'),
        use_template: zod
            .string()
            .optional()
            .describe('Template key to create the dashboard from a predefined template.'),
        use_dashboard: zod.number().nullish().describe('ID of an existing dashboard to duplicate.'),
        delete_insights: zod
            .boolean()
            .default(dashboardsCreateUnlistedDashboardCreateBodyDeleteInsightsDefault)
            .describe('When deleting, also delete insights that are only on this dashboard.'),
        _create_in_folder: zod.string().optional(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const dataColorThemesListResponseResultsItemNameMax = 100

export const dataColorThemesListResponseResultsItemCreatedByOneDistinctIdMax = 200

export const dataColorThemesListResponseResultsItemCreatedByOneFirstNameMax = 150

export const dataColorThemesListResponseResultsItemCreatedByOneLastNameMax = 150

export const dataColorThemesListResponseResultsItemCreatedByOneEmailMax = 254

export const DataColorThemesListResponse = /* @__PURE__ */ zod.object({
    count: zod.number(),
    next: zod.url().nullish(),
    previous: zod.url().nullish(),
    results: zod.array(
        zod.object({
            id: zod.number(),
            name: zod.string().max(dataColorThemesListResponseResultsItemNameMax),
            colors: zod.unknown().optional(),
            is_global: zod.boolean(),
            created_at: zod.iso.datetime({}).nullable(),
            created_by: zod.object({
                id: zod.number(),
                uuid: zod.uuid(),
                distinct_id: zod
                    .string()
                    .max(dataColorThemesListResponseResultsItemCreatedByOneDistinctIdMax)
                    .nullish(),
                first_name: zod.string().max(dataColorThemesListResponseResultsItemCreatedByOneFirstNameMax).optional(),
                last_name: zod.string().max(dataColorThemesListResponseResultsItemCreatedByOneLastNameMax).optional(),
                email: zod.email().max(dataColorThemesListResponseResultsItemCreatedByOneEmailMax),
                is_email_verified: zod.boolean().nullish(),
                hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
                role_at_organization: zod
                    .union([
                        zod
                            .enum([
                                'engineering',
                                'data',
                                'product',
                                'founder',
                                'leadership',
                                'marketing',
                                'sales',
                                'other',
                            ])
                            .describe(
                                '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                            ),
                        zod.enum(['']),
                        zod.literal(null),
                    ])
                    .nullish(),
            }),
        })
    ),
})

export const dataColorThemesCreateBodyNameMax = 100

export const DataColorThemesCreateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesCreateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const dataColorThemesRetrieveResponseNameMax = 100

export const dataColorThemesRetrieveResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesRetrieveResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesRetrieveResponseCreatedByOneLastNameMax = 150

export const dataColorThemesRetrieveResponseCreatedByOneEmailMax = 254

export const DataColorThemesRetrieveResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(dataColorThemesRetrieveResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.boolean(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dataColorThemesRetrieveResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dataColorThemesRetrieveResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
})

export const dataColorThemesUpdateBodyNameMax = 100

export const DataColorThemesUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesUpdateBodyNameMax),
    colors: zod.unknown().optional(),
})

export const dataColorThemesUpdateResponseNameMax = 100

export const dataColorThemesUpdateResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesUpdateResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesUpdateResponseCreatedByOneLastNameMax = 150

export const dataColorThemesUpdateResponseCreatedByOneEmailMax = 254

export const DataColorThemesUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(dataColorThemesUpdateResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.boolean(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dataColorThemesUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dataColorThemesUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dataColorThemesUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dataColorThemesUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
})

export const dataColorThemesPartialUpdateBodyNameMax = 100

export const DataColorThemesPartialUpdateBody = /* @__PURE__ */ zod.object({
    name: zod.string().max(dataColorThemesPartialUpdateBodyNameMax).optional(),
    colors: zod.unknown().optional(),
})

export const dataColorThemesPartialUpdateResponseNameMax = 100

export const dataColorThemesPartialUpdateResponseCreatedByOneDistinctIdMax = 200

export const dataColorThemesPartialUpdateResponseCreatedByOneFirstNameMax = 150

export const dataColorThemesPartialUpdateResponseCreatedByOneLastNameMax = 150

export const dataColorThemesPartialUpdateResponseCreatedByOneEmailMax = 254

export const DataColorThemesPartialUpdateResponse = /* @__PURE__ */ zod.object({
    id: zod.number(),
    name: zod.string().max(dataColorThemesPartialUpdateResponseNameMax),
    colors: zod.unknown().optional(),
    is_global: zod.boolean(),
    created_at: zod.iso.datetime({}).nullable(),
    created_by: zod.object({
        id: zod.number(),
        uuid: zod.uuid(),
        distinct_id: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneDistinctIdMax).nullish(),
        first_name: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneFirstNameMax).optional(),
        last_name: zod.string().max(dataColorThemesPartialUpdateResponseCreatedByOneLastNameMax).optional(),
        email: zod.email().max(dataColorThemesPartialUpdateResponseCreatedByOneEmailMax),
        is_email_verified: zod.boolean().nullish(),
        hedgehog_config: zod.record(zod.string(), zod.unknown()).nullable(),
        role_at_organization: zod
            .union([
                zod
                    .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
                    .describe(
                        '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
    }),
})
