/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - core
 * OpenAPI spec version: 1.0.0
 */
import * as zod from 'zod'

export const domainsCreateBodyDomainMax = 128

export const domainsCreateBodySsoEnforcementMax = 28

export const domainsCreateBodySamlEntityIdMax = 512

export const domainsCreateBodySamlAcsUrlMax = 512

export const DomainsCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsUpdateBodyDomainMax = 128

export const domainsUpdateBodySsoEnforcementMax = 28

export const domainsUpdateBodySamlEntityIdMax = 512

export const domainsUpdateBodySamlAcsUrlMax = 512

export const DomainsUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsUpdateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsUpdateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsUpdateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsPartialUpdateBodyDomainMax = 128

export const domainsPartialUpdateBodySsoEnforcementMax = 28

export const domainsPartialUpdateBodySamlEntityIdMax = 512

export const domainsPartialUpdateBodySamlAcsUrlMax = 512

export const DomainsPartialUpdateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsPartialUpdateBodyDomainMax).optional(),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsPartialUpdateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsPartialUpdateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsPartialUpdateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

/**
 * Regenerate SCIM bearer token.
 */
export const domainsScimTokenCreateBodyDomainMax = 128

export const domainsScimTokenCreateBodySsoEnforcementMax = 28

export const domainsScimTokenCreateBodySamlEntityIdMax = 512

export const domainsScimTokenCreateBodySamlAcsUrlMax = 512

export const DomainsScimTokenCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsScimTokenCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsScimTokenCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsScimTokenCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsScimTokenCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const domainsVerifyCreateBodyDomainMax = 128

export const domainsVerifyCreateBodySsoEnforcementMax = 28

export const domainsVerifyCreateBodySamlEntityIdMax = 512

export const domainsVerifyCreateBodySamlAcsUrlMax = 512

export const DomainsVerifyCreateBody = /* @__PURE__ */ zod.object({
    domain: zod.string().max(domainsVerifyCreateBodyDomainMax),
    jit_provisioning_enabled: zod.boolean().optional(),
    sso_enforcement: zod.string().max(domainsVerifyCreateBodySsoEnforcementMax).optional(),
    saml_entity_id: zod.string().max(domainsVerifyCreateBodySamlEntityIdMax).nullish(),
    saml_acs_url: zod.string().max(domainsVerifyCreateBodySamlAcsUrlMax).nullish(),
    saml_x509_cert: zod.string().nullish(),
    scim_enabled: zod.boolean().optional(),
})

export const invitesCreateBodyTargetEmailMax = 254

export const invitesCreateBodyFirstNameMax = 30

export const invitesCreateBodySendEmailDefault = true
export const invitesCreateBodyCombinePendingInvitesDefault = false

export const InvitesCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .nullish()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesCreateBodyCombinePendingInvitesDefault),
})

export const invitesBulkCreateBodyTargetEmailMax = 254

export const invitesBulkCreateBodyFirstNameMax = 30

export const invitesBulkCreateBodySendEmailDefault = true
export const invitesBulkCreateBodyCombinePendingInvitesDefault = false

export const InvitesBulkCreateBody = /* @__PURE__ */ zod.object({
    target_email: zod.email().max(invitesBulkCreateBodyTargetEmailMax),
    first_name: zod.string().max(invitesBulkCreateBodyFirstNameMax).optional(),
    level: zod
        .union([zod.literal(1), zod.literal(8), zod.literal(15)])
        .describe('* `1` - member\n* `8` - administrator\n* `15` - owner')
        .optional(),
    message: zod.string().nullish(),
    private_project_access: zod
        .unknown()
        .nullish()
        .describe('List of team IDs and corresponding access levels to private projects.'),
    send_email: zod.boolean().default(invitesBulkCreateBodySendEmailDefault),
    combine_pending_invites: zod.boolean().default(invitesBulkCreateBodyCombinePendingInvitesDefault),
})

/**
 * Projects for the current organization.
 */
export const create2BodyNameMax = 200

export const create2BodyProductDescriptionMax = 1000

export const create2BodyAppUrlsItemMax = 200

export const create2BodyPersonDisplayNamePropertiesItemMax = 400

export const create2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const create2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const create2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const create2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const create2BodyRecordingDomainsItemMax = 200

export const Create2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(create2BodyNameMax).optional().describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(create2BodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(create2BodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(create2BodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(create2BodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(create2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(create2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(create2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(create2BodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Replace a project and its settings. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const update2BodyNameMax = 200

export const update2BodyProductDescriptionMax = 1000

export const update2BodyAppUrlsItemMax = 200

export const update2BodyPersonDisplayNamePropertiesItemMax = 400

export const update2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const update2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const update2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const update2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const update2BodyRecordingDomainsItemMax = 200

export const Update2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(update2BodyNameMax).optional().describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(update2BodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(update2BodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(update2BodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(update2BodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(update2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(update2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(update2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(update2BodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Update one or more of a project's settings. Only the fields included in the request body are changed.
 */
export const partialUpdate2BodyNameMax = 200

export const partialUpdate2BodyProductDescriptionMax = 1000

export const partialUpdate2BodyAppUrlsItemMax = 200

export const partialUpdate2BodyPersonDisplayNamePropertiesItemMax = 400

export const partialUpdate2BodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMin = 0
export const partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const partialUpdate2BodySessionRecordingTriggerMatchTypeConfigMax = 24

export const partialUpdate2BodyRecordingDomainsItemMax = 200

export const PartialUpdate2Body = /* @__PURE__ */ zod
    .object({
        name: zod.string().min(1).max(partialUpdate2BodyNameMax).optional().describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(partialUpdate2BodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(partialUpdate2BodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(partialUpdate2BodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(partialUpdate2BodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMin)
            .max(partialUpdate2BodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(partialUpdate2BodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(partialUpdate2BodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const addProductIntentPartialUpdateBodyNameMax = 200

export const addProductIntentPartialUpdateBodyProductDescriptionMax = 1000

export const addProductIntentPartialUpdateBodyAppUrlsItemMax = 200

export const addProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const addProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const addProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const addProductIntentPartialUpdateBodyRecordingDomainsItemMax = 200

export const AddProductIntentPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(addProductIntentPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(addProductIntentPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(addProductIntentPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(addProductIntentPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(addProductIntentPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(addProductIntentPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(addProductIntentPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(addProductIntentPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const changeOrganizationCreateBodyNameMax = 200

export const changeOrganizationCreateBodyProductDescriptionMax = 1000

export const changeOrganizationCreateBodyAppUrlsItemMax = 200

export const changeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const changeOrganizationCreateBodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const changeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const changeOrganizationCreateBodyRecordingDomainsItemMax = 200

export const ChangeOrganizationCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(changeOrganizationCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(changeOrganizationCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(changeOrganizationCreateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(changeOrganizationCreateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(changeOrganizationCreateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(changeOrganizationCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(changeOrganizationCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(changeOrganizationCreateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const completeProductOnboardingPartialUpdateBodyNameMax = 200

export const completeProductOnboardingPartialUpdateBodyProductDescriptionMax = 1000

export const completeProductOnboardingPartialUpdateBodyAppUrlsItemMax = 200

export const completeProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const completeProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const completeProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const completeProductOnboardingPartialUpdateBodyRecordingDomainsItemMax = 200

export const CompleteProductOnboardingPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(completeProductOnboardingPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(completeProductOnboardingPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(completeProductOnboardingPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(completeProductOnboardingPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(completeProductOnboardingPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(completeProductOnboardingPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const deleteSecretTokenBackupPartialUpdateBodyNameMax = 200

export const deleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax = 1000

export const deleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax = 200

export const deleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const deleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const deleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax = 200

export const DeleteSecretTokenBackupPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(deleteSecretTokenBackupPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(deleteSecretTokenBackupPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(deleteSecretTokenBackupPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(deleteSecretTokenBackupPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(deleteSecretTokenBackupPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const generateConversationsPublicTokenCreateBodyNameMax = 200

export const generateConversationsPublicTokenCreateBodyProductDescriptionMax = 1000

export const generateConversationsPublicTokenCreateBodyAppUrlsItemMax = 200

export const generateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax = 400

export const generateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const generateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const generateConversationsPublicTokenCreateBodyRecordingDomainsItemMax = 200

export const GenerateConversationsPublicTokenCreateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(generateConversationsPublicTokenCreateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(generateConversationsPublicTokenCreateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyAppUrlsItemMax).nullable())
            .optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(generateConversationsPublicTokenCreateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(generateConversationsPublicTokenCreateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(generateConversationsPublicTokenCreateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(generateConversationsPublicTokenCreateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const resetTokenPartialUpdateBodyNameMax = 200

export const resetTokenPartialUpdateBodyProductDescriptionMax = 1000

export const resetTokenPartialUpdateBodyAppUrlsItemMax = 200

export const resetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const resetTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp('^-?\\d{0,1}(?:\\.\\d{0,2})?$')
export const resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const resetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const resetTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const ResetTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(resetTokenPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(resetTokenPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(resetTokenPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(resetTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(resetTokenPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(resetTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(resetTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(resetTokenPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

/**
 * Projects for the current organization.
 */
export const rotateSecretTokenPartialUpdateBodyNameMax = 200

export const rotateSecretTokenPartialUpdateBodyProductDescriptionMax = 1000

export const rotateSecretTokenPartialUpdateBodyAppUrlsItemMax = 200

export const rotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax = 400

export const rotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp = new RegExp(
    '^-?\\d{0,1}(?:\\.\\d{0,2})?$'
)
export const rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin = 0
export const rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax = 30000

export const rotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax = 24

export const rotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax = 200

export const RotateSecretTokenPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        name: zod
            .string()
            .min(1)
            .max(rotateSecretTokenPartialUpdateBodyNameMax)
            .optional()
            .describe('Human-readable project name.'),
        product_description: zod
            .string()
            .max(rotateSecretTokenPartialUpdateBodyProductDescriptionMax)
            .nullish()
            .describe(
                'Short description of what the project is about. This is helpful to give our AI agents context about your project.'
            ),
        app_urls: zod.array(zod.string().max(rotateSecretTokenPartialUpdateBodyAppUrlsItemMax).nullable()).optional(),
        anonymize_ips: zod
            .boolean()
            .optional()
            .describe('When true, PostHog drops the IP address from every ingested event.'),
        completed_snippet_onboarding: zod.boolean().optional(),
        test_account_filters: zod
            .unknown()
            .optional()
            .describe('Filter groups that identify internal/test traffic to be excluded from insights.'),
        test_account_filters_default_checked: zod
            .boolean()
            .nullish()
            .describe('When true, new insights default to excluding internal/test users.'),
        path_cleaning_filters: zod
            .unknown()
            .nullish()
            .describe(
                'Regex rewrite rules that collapse dynamic path segments (e.g. user IDs) before displaying URLs in paths.'
            ),
        is_demo: zod.boolean().optional(),
        timezone: zod
            .string()
            .optional()
            .describe(
                'IANA timezone used for date-based filters and reporting (e.g. `America/Los_Angeles`).\n\n* `Africa/Abidjan` - Africa/Abidjan\n* `Africa/Accra` - Africa/Accra\n* `Africa/Addis_Ababa` - Africa/Addis_Ababa\n* `Africa/Algiers` - Africa/Algiers\n* `Africa/Asmara` - Africa/Asmara\n* `Africa/Asmera` - Africa/Asmera\n* `Africa/Bamako` - Africa/Bamako\n* `Africa/Bangui` - Africa/Bangui\n* `Africa/Banjul` - Africa/Banjul\n* `Africa/Bissau` - Africa/Bissau\n* `Africa/Blantyre` - Africa/Blantyre\n* `Africa/Brazzaville` - Africa/Brazzaville\n* `Africa/Bujumbura` - Africa/Bujumbura\n* `Africa/Cairo` - Africa/Cairo\n* `Africa/Casablanca` - Africa/Casablanca\n* `Africa/Ceuta` - Africa/Ceuta\n* `Africa/Conakry` - Africa/Conakry\n* `Africa/Dakar` - Africa/Dakar\n* `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam\n* `Africa/Djibouti` - Africa/Djibouti\n* `Africa/Douala` - Africa/Douala\n* `Africa/El_Aaiun` - Africa/El_Aaiun\n* `Africa/Freetown` - Africa/Freetown\n* `Africa/Gaborone` - Africa/Gaborone\n* `Africa/Harare` - Africa/Harare\n* `Africa/Johannesburg` - Africa/Johannesburg\n* `Africa/Juba` - Africa/Juba\n* `Africa/Kampala` - Africa/Kampala\n* `Africa/Khartoum` - Africa/Khartoum\n* `Africa/Kigali` - Africa/Kigali\n* `Africa/Kinshasa` - Africa/Kinshasa\n* `Africa/Lagos` - Africa/Lagos\n* `Africa/Libreville` - Africa/Libreville\n* `Africa/Lome` - Africa/Lome\n* `Africa/Luanda` - Africa/Luanda\n* `Africa/Lubumbashi` - Africa/Lubumbashi\n* `Africa/Lusaka` - Africa/Lusaka\n* `Africa/Malabo` - Africa/Malabo\n* `Africa/Maputo` - Africa/Maputo\n* `Africa/Maseru` - Africa/Maseru\n* `Africa/Mbabane` - Africa/Mbabane\n* `Africa/Mogadishu` - Africa/Mogadishu\n* `Africa/Monrovia` - Africa/Monrovia\n* `Africa/Nairobi` - Africa/Nairobi\n* `Africa/Ndjamena` - Africa/Ndjamena\n* `Africa/Niamey` - Africa/Niamey\n* `Africa/Nouakchott` - Africa/Nouakchott\n* `Africa/Ouagadougou` - Africa/Ouagadougou\n* `Africa/Porto-Novo` - Africa/Porto-Novo\n* `Africa/Sao_Tome` - Africa/Sao_Tome\n* `Africa/Timbuktu` - Africa/Timbuktu\n* `Africa/Tripoli` - Africa/Tripoli\n* `Africa/Tunis` - Africa/Tunis\n* `Africa/Windhoek` - Africa/Windhoek\n* `America/Adak` - America/Adak\n* `America/Anchorage` - America/Anchorage\n* `America/Anguilla` - America/Anguilla\n* `America/Antigua` - America/Antigua\n* `America/Araguaina` - America/Araguaina\n* `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires\n* `America/Argentina/Catamarca` - America/Argentina/Catamarca\n* `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia\n* `America/Argentina/Cordoba` - America/Argentina/Cordoba\n* `America/Argentina/Jujuy` - America/Argentina/Jujuy\n* `America/Argentina/La_Rioja` - America/Argentina/La_Rioja\n* `America/Argentina/Mendoza` - America/Argentina/Mendoza\n* `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos\n* `America/Argentina/Salta` - America/Argentina/Salta\n* `America/Argentina/San_Juan` - America/Argentina/San_Juan\n* `America/Argentina/San_Luis` - America/Argentina/San_Luis\n* `America/Argentina/Tucuman` - America/Argentina/Tucuman\n* `America/Argentina/Ushuaia` - America/Argentina/Ushuaia\n* `America/Aruba` - America/Aruba\n* `America/Asuncion` - America/Asuncion\n* `America/Atikokan` - America/Atikokan\n* `America/Atka` - America/Atka\n* `America/Bahia` - America/Bahia\n* `America/Bahia_Banderas` - America/Bahia_Banderas\n* `America/Barbados` - America/Barbados\n* `America/Belem` - America/Belem\n* `America/Belize` - America/Belize\n* `America/Blanc-Sablon` - America/Blanc-Sablon\n* `America/Boa_Vista` - America/Boa_Vista\n* `America/Bogota` - America/Bogota\n* `America/Boise` - America/Boise\n* `America/Buenos_Aires` - America/Buenos_Aires\n* `America/Cambridge_Bay` - America/Cambridge_Bay\n* `America/Campo_Grande` - America/Campo_Grande\n* `America/Cancun` - America/Cancun\n* `America/Caracas` - America/Caracas\n* `America/Catamarca` - America/Catamarca\n* `America/Cayenne` - America/Cayenne\n* `America/Cayman` - America/Cayman\n* `America/Chicago` - America/Chicago\n* `America/Chihuahua` - America/Chihuahua\n* `America/Ciudad_Juarez` - America/Ciudad_Juarez\n* `America/Coral_Harbour` - America/Coral_Harbour\n* `America/Cordoba` - America/Cordoba\n* `America/Costa_Rica` - America/Costa_Rica\n* `America/Creston` - America/Creston\n* `America/Cuiaba` - America/Cuiaba\n* `America/Curacao` - America/Curacao\n* `America/Danmarkshavn` - America/Danmarkshavn\n* `America/Dawson` - America/Dawson\n* `America/Dawson_Creek` - America/Dawson_Creek\n* `America/Denver` - America/Denver\n* `America/Detroit` - America/Detroit\n* `America/Dominica` - America/Dominica\n* `America/Edmonton` - America/Edmonton\n* `America/Eirunepe` - America/Eirunepe\n* `America/El_Salvador` - America/El_Salvador\n* `America/Ensenada` - America/Ensenada\n* `America/Fort_Nelson` - America/Fort_Nelson\n* `America/Fort_Wayne` - America/Fort_Wayne\n* `America/Fortaleza` - America/Fortaleza\n* `America/Glace_Bay` - America/Glace_Bay\n* `America/Godthab` - America/Godthab\n* `America/Goose_Bay` - America/Goose_Bay\n* `America/Grand_Turk` - America/Grand_Turk\n* `America/Grenada` - America/Grenada\n* `America/Guadeloupe` - America/Guadeloupe\n* `America/Guatemala` - America/Guatemala\n* `America/Guayaquil` - America/Guayaquil\n* `America/Guyana` - America/Guyana\n* `America/Halifax` - America/Halifax\n* `America/Havana` - America/Havana\n* `America/Hermosillo` - America/Hermosillo\n* `America/Indiana/Indianapolis` - America/Indiana/Indianapolis\n* `America/Indiana/Knox` - America/Indiana/Knox\n* `America/Indiana/Marengo` - America/Indiana/Marengo\n* `America/Indiana/Petersburg` - America/Indiana/Petersburg\n* `America/Indiana/Tell_City` - America/Indiana/Tell_City\n* `America/Indiana/Vevay` - America/Indiana/Vevay\n* `America/Indiana/Vincennes` - America/Indiana/Vincennes\n* `America/Indiana/Winamac` - America/Indiana/Winamac\n* `America/Indianapolis` - America/Indianapolis\n* `America/Inuvik` - America/Inuvik\n* `America/Iqaluit` - America/Iqaluit\n* `America/Jamaica` - America/Jamaica\n* `America/Jujuy` - America/Jujuy\n* `America/Juneau` - America/Juneau\n* `America/Kentucky/Louisville` - America/Kentucky/Louisville\n* `America/Kentucky/Monticello` - America/Kentucky/Monticello\n* `America/Knox_IN` - America/Knox_IN\n* `America/Kralendijk` - America/Kralendijk\n* `America/La_Paz` - America/La_Paz\n* `America/Lima` - America/Lima\n* `America/Los_Angeles` - America/Los_Angeles\n* `America/Louisville` - America/Louisville\n* `America/Lower_Princes` - America/Lower_Princes\n* `America/Maceio` - America/Maceio\n* `America/Managua` - America/Managua\n* `America/Manaus` - America/Manaus\n* `America/Marigot` - America/Marigot\n* `America/Martinique` - America/Martinique\n* `America/Matamoros` - America/Matamoros\n* `America/Mazatlan` - America/Mazatlan\n* `America/Mendoza` - America/Mendoza\n* `America/Menominee` - America/Menominee\n* `America/Merida` - America/Merida\n* `America/Metlakatla` - America/Metlakatla\n* `America/Mexico_City` - America/Mexico_City\n* `America/Miquelon` - America/Miquelon\n* `America/Moncton` - America/Moncton\n* `America/Monterrey` - America/Monterrey\n* `America/Montevideo` - America/Montevideo\n* `America/Montreal` - America/Montreal\n* `America/Montserrat` - America/Montserrat\n* `America/Nassau` - America/Nassau\n* `America/New_York` - America/New_York\n* `America/Nipigon` - America/Nipigon\n* `America/Nome` - America/Nome\n* `America/Noronha` - America/Noronha\n* `America/North_Dakota/Beulah` - America/North_Dakota/Beulah\n* `America/North_Dakota/Center` - America/North_Dakota/Center\n* `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem\n* `America/Nuuk` - America/Nuuk\n* `America/Ojinaga` - America/Ojinaga\n* `America/Panama` - America/Panama\n* `America/Pangnirtung` - America/Pangnirtung\n* `America/Paramaribo` - America/Paramaribo\n* `America/Phoenix` - America/Phoenix\n* `America/Port-au-Prince` - America/Port-au-Prince\n* `America/Port_of_Spain` - America/Port_of_Spain\n* `America/Porto_Acre` - America/Porto_Acre\n* `America/Porto_Velho` - America/Porto_Velho\n* `America/Puerto_Rico` - America/Puerto_Rico\n* `America/Punta_Arenas` - America/Punta_Arenas\n* `America/Rainy_River` - America/Rainy_River\n* `America/Rankin_Inlet` - America/Rankin_Inlet\n* `America/Recife` - America/Recife\n* `America/Regina` - America/Regina\n* `America/Resolute` - America/Resolute\n* `America/Rio_Branco` - America/Rio_Branco\n* `America/Rosario` - America/Rosario\n* `America/Santa_Isabel` - America/Santa_Isabel\n* `America/Santarem` - America/Santarem\n* `America/Santiago` - America/Santiago\n* `America/Santo_Domingo` - America/Santo_Domingo\n* `America/Sao_Paulo` - America/Sao_Paulo\n* `America/Scoresbysund` - America/Scoresbysund\n* `America/Shiprock` - America/Shiprock\n* `America/Sitka` - America/Sitka\n* `America/St_Barthelemy` - America/St_Barthelemy\n* `America/St_Johns` - America/St_Johns\n* `America/St_Kitts` - America/St_Kitts\n* `America/St_Lucia` - America/St_Lucia\n* `America/St_Thomas` - America/St_Thomas\n* `America/St_Vincent` - America/St_Vincent\n* `America/Swift_Current` - America/Swift_Current\n* `America/Tegucigalpa` - America/Tegucigalpa\n* `America/Thule` - America/Thule\n* `America/Thunder_Bay` - America/Thunder_Bay\n* `America/Tijuana` - America/Tijuana\n* `America/Toronto` - America/Toronto\n* `America/Tortola` - America/Tortola\n* `America/Vancouver` - America/Vancouver\n* `America/Virgin` - America/Virgin\n* `America/Whitehorse` - America/Whitehorse\n* `America/Winnipeg` - America/Winnipeg\n* `America/Yakutat` - America/Yakutat\n* `America/Yellowknife` - America/Yellowknife\n* `Antarctica/Casey` - Antarctica/Casey\n* `Antarctica/Davis` - Antarctica/Davis\n* `Antarctica/DumontDUrville` - Antarctica/DumontDUrville\n* `Antarctica/Macquarie` - Antarctica/Macquarie\n* `Antarctica/Mawson` - Antarctica/Mawson\n* `Antarctica/McMurdo` - Antarctica/McMurdo\n* `Antarctica/Palmer` - Antarctica/Palmer\n* `Antarctica/Rothera` - Antarctica/Rothera\n* `Antarctica/South_Pole` - Antarctica/South_Pole\n* `Antarctica/Syowa` - Antarctica/Syowa\n* `Antarctica/Troll` - Antarctica/Troll\n* `Antarctica/Vostok` - Antarctica/Vostok\n* `Arctic/Longyearbyen` - Arctic/Longyearbyen\n* `Asia/Aden` - Asia/Aden\n* `Asia/Almaty` - Asia/Almaty\n* `Asia/Amman` - Asia/Amman\n* `Asia/Anadyr` - Asia/Anadyr\n* `Asia/Aqtau` - Asia/Aqtau\n* `Asia/Aqtobe` - Asia/Aqtobe\n* `Asia/Ashgabat` - Asia/Ashgabat\n* `Asia/Ashkhabad` - Asia/Ashkhabad\n* `Asia/Atyrau` - Asia/Atyrau\n* `Asia/Baghdad` - Asia/Baghdad\n* `Asia/Bahrain` - Asia/Bahrain\n* `Asia/Baku` - Asia/Baku\n* `Asia/Bangkok` - Asia/Bangkok\n* `Asia/Barnaul` - Asia/Barnaul\n* `Asia/Beirut` - Asia/Beirut\n* `Asia/Bishkek` - Asia/Bishkek\n* `Asia/Brunei` - Asia/Brunei\n* `Asia/Calcutta` - Asia/Calcutta\n* `Asia/Chita` - Asia/Chita\n* `Asia/Choibalsan` - Asia/Choibalsan\n* `Asia/Chongqing` - Asia/Chongqing\n* `Asia/Chungking` - Asia/Chungking\n* `Asia/Colombo` - Asia/Colombo\n* `Asia/Dacca` - Asia/Dacca\n* `Asia/Damascus` - Asia/Damascus\n* `Asia/Dhaka` - Asia/Dhaka\n* `Asia/Dili` - Asia/Dili\n* `Asia/Dubai` - Asia/Dubai\n* `Asia/Dushanbe` - Asia/Dushanbe\n* `Asia/Famagusta` - Asia/Famagusta\n* `Asia/Gaza` - Asia/Gaza\n* `Asia/Harbin` - Asia/Harbin\n* `Asia/Hebron` - Asia/Hebron\n* `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh\n* `Asia/Hong_Kong` - Asia/Hong_Kong\n* `Asia/Hovd` - Asia/Hovd\n* `Asia/Irkutsk` - Asia/Irkutsk\n* `Asia/Istanbul` - Asia/Istanbul\n* `Asia/Jakarta` - Asia/Jakarta\n* `Asia/Jayapura` - Asia/Jayapura\n* `Asia/Jerusalem` - Asia/Jerusalem\n* `Asia/Kabul` - Asia/Kabul\n* `Asia/Kamchatka` - Asia/Kamchatka\n* `Asia/Karachi` - Asia/Karachi\n* `Asia/Kashgar` - Asia/Kashgar\n* `Asia/Kathmandu` - Asia/Kathmandu\n* `Asia/Katmandu` - Asia/Katmandu\n* `Asia/Khandyga` - Asia/Khandyga\n* `Asia/Kolkata` - Asia/Kolkata\n* `Asia/Krasnoyarsk` - Asia/Krasnoyarsk\n* `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur\n* `Asia/Kuching` - Asia/Kuching\n* `Asia/Kuwait` - Asia/Kuwait\n* `Asia/Macao` - Asia/Macao\n* `Asia/Macau` - Asia/Macau\n* `Asia/Magadan` - Asia/Magadan\n* `Asia/Makassar` - Asia/Makassar\n* `Asia/Manila` - Asia/Manila\n* `Asia/Muscat` - Asia/Muscat\n* `Asia/Nicosia` - Asia/Nicosia\n* `Asia/Novokuznetsk` - Asia/Novokuznetsk\n* `Asia/Novosibirsk` - Asia/Novosibirsk\n* `Asia/Omsk` - Asia/Omsk\n* `Asia/Oral` - Asia/Oral\n* `Asia/Phnom_Penh` - Asia/Phnom_Penh\n* `Asia/Pontianak` - Asia/Pontianak\n* `Asia/Pyongyang` - Asia/Pyongyang\n* `Asia/Qatar` - Asia/Qatar\n* `Asia/Qostanay` - Asia/Qostanay\n* `Asia/Qyzylorda` - Asia/Qyzylorda\n* `Asia/Rangoon` - Asia/Rangoon\n* `Asia/Riyadh` - Asia/Riyadh\n* `Asia/Saigon` - Asia/Saigon\n* `Asia/Sakhalin` - Asia/Sakhalin\n* `Asia/Samarkand` - Asia/Samarkand\n* `Asia/Seoul` - Asia/Seoul\n* `Asia/Shanghai` - Asia/Shanghai\n* `Asia/Singapore` - Asia/Singapore\n* `Asia/Srednekolymsk` - Asia/Srednekolymsk\n* `Asia/Taipei` - Asia/Taipei\n* `Asia/Tashkent` - Asia/Tashkent\n* `Asia/Tbilisi` - Asia/Tbilisi\n* `Asia/Tehran` - Asia/Tehran\n* `Asia/Tel_Aviv` - Asia/Tel_Aviv\n* `Asia/Thimbu` - Asia/Thimbu\n* `Asia/Thimphu` - Asia/Thimphu\n* `Asia/Tokyo` - Asia/Tokyo\n* `Asia/Tomsk` - Asia/Tomsk\n* `Asia/Ujung_Pandang` - Asia/Ujung_Pandang\n* `Asia/Ulaanbaatar` - Asia/Ulaanbaatar\n* `Asia/Ulan_Bator` - Asia/Ulan_Bator\n* `Asia/Urumqi` - Asia/Urumqi\n* `Asia/Ust-Nera` - Asia/Ust-Nera\n* `Asia/Vientiane` - Asia/Vientiane\n* `Asia/Vladivostok` - Asia/Vladivostok\n* `Asia/Yakutsk` - Asia/Yakutsk\n* `Asia/Yangon` - Asia/Yangon\n* `Asia/Yekaterinburg` - Asia/Yekaterinburg\n* `Asia/Yerevan` - Asia/Yerevan\n* `Atlantic/Azores` - Atlantic/Azores\n* `Atlantic/Bermuda` - Atlantic/Bermuda\n* `Atlantic/Canary` - Atlantic/Canary\n* `Atlantic/Cape_Verde` - Atlantic/Cape_Verde\n* `Atlantic/Faeroe` - Atlantic/Faeroe\n* `Atlantic/Faroe` - Atlantic/Faroe\n* `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen\n* `Atlantic/Madeira` - Atlantic/Madeira\n* `Atlantic/Reykjavik` - Atlantic/Reykjavik\n* `Atlantic/South_Georgia` - Atlantic/South_Georgia\n* `Atlantic/St_Helena` - Atlantic/St_Helena\n* `Atlantic/Stanley` - Atlantic/Stanley\n* `Australia/ACT` - Australia/ACT\n* `Australia/Adelaide` - Australia/Adelaide\n* `Australia/Brisbane` - Australia/Brisbane\n* `Australia/Broken_Hill` - Australia/Broken_Hill\n* `Australia/Canberra` - Australia/Canberra\n* `Australia/Currie` - Australia/Currie\n* `Australia/Darwin` - Australia/Darwin\n* `Australia/Eucla` - Australia/Eucla\n* `Australia/Hobart` - Australia/Hobart\n* `Australia/LHI` - Australia/LHI\n* `Australia/Lindeman` - Australia/Lindeman\n* `Australia/Lord_Howe` - Australia/Lord_Howe\n* `Australia/Melbourne` - Australia/Melbourne\n* `Australia/NSW` - Australia/NSW\n* `Australia/North` - Australia/North\n* `Australia/Perth` - Australia/Perth\n* `Australia/Queensland` - Australia/Queensland\n* `Australia/South` - Australia/South\n* `Australia/Sydney` - Australia/Sydney\n* `Australia/Tasmania` - Australia/Tasmania\n* `Australia/Victoria` - Australia/Victoria\n* `Australia/West` - Australia/West\n* `Australia/Yancowinna` - Australia/Yancowinna\n* `Brazil/Acre` - Brazil/Acre\n* `Brazil/DeNoronha` - Brazil/DeNoronha\n* `Brazil/East` - Brazil/East\n* `Brazil/West` - Brazil/West\n* `CET` - CET\n* `CST6CDT` - CST6CDT\n* `Canada/Atlantic` - Canada/Atlantic\n* `Canada/Central` - Canada/Central\n* `Canada/Eastern` - Canada/Eastern\n* `Canada/Mountain` - Canada/Mountain\n* `Canada/Newfoundland` - Canada/Newfoundland\n* `Canada/Pacific` - Canada/Pacific\n* `Canada/Saskatchewan` - Canada/Saskatchewan\n* `Canada/Yukon` - Canada/Yukon\n* `Chile/Continental` - Chile/Continental\n* `Chile/EasterIsland` - Chile/EasterIsland\n* `Cuba` - Cuba\n* `EET` - EET\n* `EST` - EST\n* `EST5EDT` - EST5EDT\n* `Egypt` - Egypt\n* `Eire` - Eire\n* `Etc/GMT` - Etc/GMT\n* `Etc/GMT+0` - Etc/GMT+0\n* `Etc/GMT+1` - Etc/GMT+1\n* `Etc/GMT+10` - Etc/GMT+10\n* `Etc/GMT+11` - Etc/GMT+11\n* `Etc/GMT+12` - Etc/GMT+12\n* `Etc/GMT+2` - Etc/GMT+2\n* `Etc/GMT+3` - Etc/GMT+3\n* `Etc/GMT+4` - Etc/GMT+4\n* `Etc/GMT+5` - Etc/GMT+5\n* `Etc/GMT+6` - Etc/GMT+6\n* `Etc/GMT+7` - Etc/GMT+7\n* `Etc/GMT+8` - Etc/GMT+8\n* `Etc/GMT+9` - Etc/GMT+9\n* `Etc/GMT-0` - Etc/GMT-0\n* `Etc/GMT-1` - Etc/GMT-1\n* `Etc/GMT-10` - Etc/GMT-10\n* `Etc/GMT-11` - Etc/GMT-11\n* `Etc/GMT-12` - Etc/GMT-12\n* `Etc/GMT-13` - Etc/GMT-13\n* `Etc/GMT-14` - Etc/GMT-14\n* `Etc/GMT-2` - Etc/GMT-2\n* `Etc/GMT-3` - Etc/GMT-3\n* `Etc/GMT-4` - Etc/GMT-4\n* `Etc/GMT-5` - Etc/GMT-5\n* `Etc/GMT-6` - Etc/GMT-6\n* `Etc/GMT-7` - Etc/GMT-7\n* `Etc/GMT-8` - Etc/GMT-8\n* `Etc/GMT-9` - Etc/GMT-9\n* `Etc/GMT0` - Etc/GMT0\n* `Etc/Greenwich` - Etc/Greenwich\n* `Etc/UCT` - Etc/UCT\n* `Etc/UTC` - Etc/UTC\n* `Etc/Universal` - Etc/Universal\n* `Etc/Zulu` - Etc/Zulu\n* `Europe/Amsterdam` - Europe/Amsterdam\n* `Europe/Andorra` - Europe/Andorra\n* `Europe/Astrakhan` - Europe/Astrakhan\n* `Europe/Athens` - Europe/Athens\n* `Europe/Belfast` - Europe/Belfast\n* `Europe/Belgrade` - Europe/Belgrade\n* `Europe/Berlin` - Europe/Berlin\n* `Europe/Bratislava` - Europe/Bratislava\n* `Europe/Brussels` - Europe/Brussels\n* `Europe/Bucharest` - Europe/Bucharest\n* `Europe/Budapest` - Europe/Budapest\n* `Europe/Busingen` - Europe/Busingen\n* `Europe/Chisinau` - Europe/Chisinau\n* `Europe/Copenhagen` - Europe/Copenhagen\n* `Europe/Dublin` - Europe/Dublin\n* `Europe/Gibraltar` - Europe/Gibraltar\n* `Europe/Guernsey` - Europe/Guernsey\n* `Europe/Helsinki` - Europe/Helsinki\n* `Europe/Isle_of_Man` - Europe/Isle_of_Man\n* `Europe/Istanbul` - Europe/Istanbul\n* `Europe/Jersey` - Europe/Jersey\n* `Europe/Kaliningrad` - Europe/Kaliningrad\n* `Europe/Kiev` - Europe/Kiev\n* `Europe/Kirov` - Europe/Kirov\n* `Europe/Kyiv` - Europe/Kyiv\n* `Europe/Lisbon` - Europe/Lisbon\n* `Europe/Ljubljana` - Europe/Ljubljana\n* `Europe/London` - Europe/London\n* `Europe/Luxembourg` - Europe/Luxembourg\n* `Europe/Madrid` - Europe/Madrid\n* `Europe/Malta` - Europe/Malta\n* `Europe/Mariehamn` - Europe/Mariehamn\n* `Europe/Minsk` - Europe/Minsk\n* `Europe/Monaco` - Europe/Monaco\n* `Europe/Moscow` - Europe/Moscow\n* `Europe/Nicosia` - Europe/Nicosia\n* `Europe/Oslo` - Europe/Oslo\n* `Europe/Paris` - Europe/Paris\n* `Europe/Podgorica` - Europe/Podgorica\n* `Europe/Prague` - Europe/Prague\n* `Europe/Riga` - Europe/Riga\n* `Europe/Rome` - Europe/Rome\n* `Europe/Samara` - Europe/Samara\n* `Europe/San_Marino` - Europe/San_Marino\n* `Europe/Sarajevo` - Europe/Sarajevo\n* `Europe/Saratov` - Europe/Saratov\n* `Europe/Simferopol` - Europe/Simferopol\n* `Europe/Skopje` - Europe/Skopje\n* `Europe/Sofia` - Europe/Sofia\n* `Europe/Stockholm` - Europe/Stockholm\n* `Europe/Tallinn` - Europe/Tallinn\n* `Europe/Tirane` - Europe/Tirane\n* `Europe/Tiraspol` - Europe/Tiraspol\n* `Europe/Ulyanovsk` - Europe/Ulyanovsk\n* `Europe/Uzhgorod` - Europe/Uzhgorod\n* `Europe/Vaduz` - Europe/Vaduz\n* `Europe/Vatican` - Europe/Vatican\n* `Europe/Vienna` - Europe/Vienna\n* `Europe/Vilnius` - Europe/Vilnius\n* `Europe/Volgograd` - Europe/Volgograd\n* `Europe/Warsaw` - Europe/Warsaw\n* `Europe/Zagreb` - Europe/Zagreb\n* `Europe/Zaporozhye` - Europe/Zaporozhye\n* `Europe/Zurich` - Europe/Zurich\n* `GB` - GB\n* `GB-Eire` - GB-Eire\n* `GMT` - GMT\n* `GMT+0` - GMT+0\n* `GMT-0` - GMT-0\n* `GMT0` - GMT0\n* `Greenwich` - Greenwich\n* `HST` - HST\n* `Hongkong` - Hongkong\n* `Iceland` - Iceland\n* `Indian/Antananarivo` - Indian/Antananarivo\n* `Indian/Chagos` - Indian/Chagos\n* `Indian/Christmas` - Indian/Christmas\n* `Indian/Cocos` - Indian/Cocos\n* `Indian/Comoro` - Indian/Comoro\n* `Indian/Kerguelen` - Indian/Kerguelen\n* `Indian/Mahe` - Indian/Mahe\n* `Indian/Maldives` - Indian/Maldives\n* `Indian/Mauritius` - Indian/Mauritius\n* `Indian/Mayotte` - Indian/Mayotte\n* `Indian/Reunion` - Indian/Reunion\n* `Iran` - Iran\n* `Israel` - Israel\n* `Jamaica` - Jamaica\n* `Japan` - Japan\n* `Kwajalein` - Kwajalein\n* `Libya` - Libya\n* `MET` - MET\n* `MST` - MST\n* `MST7MDT` - MST7MDT\n* `Mexico/BajaNorte` - Mexico/BajaNorte\n* `Mexico/BajaSur` - Mexico/BajaSur\n* `Mexico/General` - Mexico/General\n* `NZ` - NZ\n* `NZ-CHAT` - NZ-CHAT\n* `Navajo` - Navajo\n* `PRC` - PRC\n* `PST8PDT` - PST8PDT\n* `Pacific/Apia` - Pacific/Apia\n* `Pacific/Auckland` - Pacific/Auckland\n* `Pacific/Bougainville` - Pacific/Bougainville\n* `Pacific/Chatham` - Pacific/Chatham\n* `Pacific/Chuuk` - Pacific/Chuuk\n* `Pacific/Easter` - Pacific/Easter\n* `Pacific/Efate` - Pacific/Efate\n* `Pacific/Enderbury` - Pacific/Enderbury\n* `Pacific/Fakaofo` - Pacific/Fakaofo\n* `Pacific/Fiji` - Pacific/Fiji\n* `Pacific/Funafuti` - Pacific/Funafuti\n* `Pacific/Galapagos` - Pacific/Galapagos\n* `Pacific/Gambier` - Pacific/Gambier\n* `Pacific/Guadalcanal` - Pacific/Guadalcanal\n* `Pacific/Guam` - Pacific/Guam\n* `Pacific/Honolulu` - Pacific/Honolulu\n* `Pacific/Johnston` - Pacific/Johnston\n* `Pacific/Kanton` - Pacific/Kanton\n* `Pacific/Kiritimati` - Pacific/Kiritimati\n* `Pacific/Kosrae` - Pacific/Kosrae\n* `Pacific/Kwajalein` - Pacific/Kwajalein\n* `Pacific/Majuro` - Pacific/Majuro\n* `Pacific/Marquesas` - Pacific/Marquesas\n* `Pacific/Midway` - Pacific/Midway\n* `Pacific/Nauru` - Pacific/Nauru\n* `Pacific/Niue` - Pacific/Niue\n* `Pacific/Norfolk` - Pacific/Norfolk\n* `Pacific/Noumea` - Pacific/Noumea\n* `Pacific/Pago_Pago` - Pacific/Pago_Pago\n* `Pacific/Palau` - Pacific/Palau\n* `Pacific/Pitcairn` - Pacific/Pitcairn\n* `Pacific/Pohnpei` - Pacific/Pohnpei\n* `Pacific/Ponape` - Pacific/Ponape\n* `Pacific/Port_Moresby` - Pacific/Port_Moresby\n* `Pacific/Rarotonga` - Pacific/Rarotonga\n* `Pacific/Saipan` - Pacific/Saipan\n* `Pacific/Samoa` - Pacific/Samoa\n* `Pacific/Tahiti` - Pacific/Tahiti\n* `Pacific/Tarawa` - Pacific/Tarawa\n* `Pacific/Tongatapu` - Pacific/Tongatapu\n* `Pacific/Truk` - Pacific/Truk\n* `Pacific/Wake` - Pacific/Wake\n* `Pacific/Wallis` - Pacific/Wallis\n* `Pacific/Yap` - Pacific/Yap\n* `Poland` - Poland\n* `Portugal` - Portugal\n* `ROC` - ROC\n* `ROK` - ROK\n* `Singapore` - Singapore\n* `Turkey` - Turkey\n* `UCT` - UCT\n* `US/Alaska` - US/Alaska\n* `US/Aleutian` - US/Aleutian\n* `US/Arizona` - US/Arizona\n* `US/Central` - US/Central\n* `US/East-Indiana` - US/East-Indiana\n* `US/Eastern` - US/Eastern\n* `US/Hawaii` - US/Hawaii\n* `US/Indiana-Starke` - US/Indiana-Starke\n* `US/Michigan` - US/Michigan\n* `US/Mountain` - US/Mountain\n* `US/Pacific` - US/Pacific\n* `US/Samoa` - US/Samoa\n* `UTC` - UTC\n* `Universal` - Universal\n* `W-SU` - W-SU\n* `WET` - WET\n* `Zulu` - Zulu'
            ),
        data_attributes: zod
            .unknown()
            .optional()
            .describe(
                "Element attributes that posthog-js should capture as action identifiers (e.g. `['data-attr']`)."
            ),
        person_display_name_properties: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateBodyPersonDisplayNamePropertiesItemMax))
            .nullish()
            .describe('Ordered list of person properties used to render a human-friendly display name in the UI.'),
        correlation_config: zod.unknown().nullish(),
        autocapture_opt_out: zod
            .boolean()
            .nullish()
            .describe('Disables posthog-js autocapture (clicks, page views) when true.'),
        autocapture_exceptions_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of JavaScript exceptions via the SDK.'),
        autocapture_web_vitals_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables automatic capture of Core Web Vitals performance metrics.'),
        autocapture_web_vitals_allowed_metrics: zod.unknown().nullish(),
        autocapture_exceptions_errors_to_ignore: zod.unknown().nullish(),
        capture_console_log_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing browser console logs alongside session replays.'),
        capture_performance_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables capturing performance timing and network requests.'),
        session_recording_opt_in: zod
            .boolean()
            .optional()
            .describe('Enables session replay recording for this project.'),
        session_recording_sample_rate: zod
            .string()
            .regex(rotateSecretTokenPartialUpdateBodySessionRecordingSampleRateRegExp)
            .nullish()
            .describe(
                'Fraction of sessions to record, as a decimal string between `0.00` and `1.00` (e.g. `0.1` = 10%).'
            ),
        session_recording_minimum_duration_milliseconds: zod
            .number()
            .min(rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMin)
            .max(rotateSecretTokenPartialUpdateBodySessionRecordingMinimumDurationMillisecondsMax)
            .nullish()
            .describe('Skip saving sessions shorter than this many milliseconds.'),
        session_recording_linked_flag: zod.unknown().nullish(),
        session_recording_network_payload_capture_config: zod.unknown().nullish(),
        session_recording_masking_config: zod.unknown().nullish(),
        session_recording_url_trigger_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_url_blocklist_config: zod.array(zod.unknown().nullable()).nullish(),
        session_recording_event_trigger_config: zod.array(zod.string().nullable()).nullish(),
        session_recording_trigger_match_type_config: zod
            .string()
            .max(rotateSecretTokenPartialUpdateBodySessionRecordingTriggerMatchTypeConfigMax)
            .nullish(),
        session_recording_trigger_groups: zod
            .unknown()
            .nullish()
            .describe(
                'V2 trigger groups configuration for session recording. If present, takes precedence over legacy trigger fields.'
            ),
        session_recording_retention_period: zod
            .enum(['30d', '90d', '1y', '5y'])
            .describe('* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years')
            .optional()
            .describe(
                'How long to retain new session recordings. One of `30d`, `90d`, `1y`, or `5y` (availability depends on plan).\n\n* `30d` - 30 Days\n* `90d` - 90 Days\n* `1y` - 1 Year\n* `5y` - 5 Years'
            ),
        session_replay_config: zod.unknown().nullish(),
        survey_config: zod.unknown().nullish(),
        access_control: zod.boolean().optional(),
        week_start_day: zod
            .union([
                zod.union([zod.literal(0), zod.literal(1)]).describe('* `0` - Sunday\n* `1` - Monday'),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'First day of the week for date range filters. 0 = Sunday, 1 = Monday.\n\n* `0` - Sunday\n* `1` - Monday'
            ),
        primary_dashboard: zod
            .number()
            .nullish()
            .describe("ID of the dashboard shown as the project's default landing dashboard."),
        live_events_columns: zod.array(zod.string()).nullish(),
        recording_domains: zod
            .array(zod.string().max(rotateSecretTokenPartialUpdateBodyRecordingDomainsItemMax).nullable())
            .nullish()
            .describe('Origins permitted to record session replays and heatmaps. Empty list allows all origins.'),
        inject_web_apps: zod.boolean().nullish(),
        extra_settings: zod.unknown().nullish(),
        modifiers: zod.unknown().nullish(),
        has_completed_onboarding_for: zod.unknown().nullish(),
        surveys_opt_in: zod
            .boolean()
            .nullish()
            .describe('Enables displaying surveys via posthog-js on allowed origins.'),
        heatmaps_opt_in: zod.boolean().nullish().describe('Enables heatmap recording on pages that host posthog-js.'),
        flags_persistence_default: zod
            .boolean()
            .nullish()
            .describe('Default value for the `persist` option on newly created feature flags.'),
        receive_org_level_activity_logs: zod.boolean().nullish(),
        business_model: zod
            .union([
                zod.enum(['b2b', 'b2c', 'other']).describe('* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish()
            .describe(
                'Whether this project serves B2B or B2C customers. Used to optimize default UI layouts.\n\n* `b2b` - B2B\n* `b2c` - B2C\n* `other` - Other'
            ),
        conversations_enabled: zod
            .boolean()
            .nullish()
            .describe('Enables the customer conversations / live chat product for this project.'),
        conversations_settings: zod.unknown().nullish(),
        logs_settings: zod.unknown().nullish(),
        proactive_tasks_enabled: zod.boolean().nullish(),
    })
    .describe(
        'Like `ProjectBasicSerializer`, but also works as a drop-in replacement for `TeamBasicSerializer` by way of\npassthrough fields. This allows the meaning of `Team` to change from \"project\" to \"environment\" without breaking\nbackward compatibility of the REST API.\nDo not use this in greenfield endpoints!'
    )

export const dashboardTemplatesUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesUpdateBodyTagsItemMax = 255

export const dashboardTemplatesUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesUpdateBodyImageUrlMax).nullish(),
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
        .array(zod.string().max(dashboardTemplatesUpdateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const dashboardTemplatesPartialUpdateBodyTemplateNameMax = 400

export const dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax = 400

export const dashboardTemplatesPartialUpdateBodyTagsItemMax = 255

export const dashboardTemplatesPartialUpdateBodyImageUrlMax = 8201

export const dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax = 255

export const DashboardTemplatesPartialUpdateBody = /* @__PURE__ */ zod.object({
    template_name: zod.string().max(dashboardTemplatesPartialUpdateBodyTemplateNameMax).nullish(),
    dashboard_description: zod.string().max(dashboardTemplatesPartialUpdateBodyDashboardDescriptionMax).nullish(),
    dashboard_filters: zod.unknown().nullish(),
    tags: zod.array(zod.string().max(dashboardTemplatesPartialUpdateBodyTagsItemMax)).nullish(),
    tiles: zod.unknown().nullish(),
    variables: zod.unknown().nullish(),
    deleted: zod.boolean().nullish(),
    image_url: zod.string().max(dashboardTemplatesPartialUpdateBodyImageUrlMax).nullish(),
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
        .array(zod.string().max(dashboardTemplatesPartialUpdateBodyAvailabilityContextsItemMax))
        .nullish(),
    is_featured: zod.boolean().optional().describe('Manually curated; used to highlight templates in the UI.'),
})

export const ExportsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod.number().nullish(),
        insight: zod.number().nullish(),
        export_format: zod
            .enum([
                'image/png',
                'application/pdf',
                'text/csv',
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'video/webm',
                'video/mp4',
                'image/gif',
                'application/json',
            ])
            .describe(
                '* `image/png` - image/png\n* `application/pdf` - application/pdf\n* `text/csv` - text/csv\n* `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` - application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\n* `video/webm` - video/webm\n* `video/mp4` - video/mp4\n* `image/gif` - image/gif\n* `application/json` - application/json'
            ),
        export_context: zod.unknown().nullish(),
    })
    .describe("Standard ExportedAsset serializer that doesn't return content.")

export const fileSystemCreateBodyTypeMax = 100

export const fileSystemCreateBodyRefMax = 100

export const FileSystemCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUpdateBodyTypeMax = 100

export const fileSystemUpdateBodyRefMax = 100

export const FileSystemUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemPartialUpdateBodyTypeMax = 100

export const fileSystemPartialUpdateBodyRefMax = 100

export const FileSystemPartialUpdateBody = /* @__PURE__ */ zod.object({
    path: zod.string().optional(),
    type: zod.string().max(fileSystemPartialUpdateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemPartialUpdateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountCreateBodyTypeMax = 100

export const fileSystemCountCreateBodyRefMax = 100

export const FileSystemCountCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLinkCreateBodyTypeMax = 100

export const fileSystemLinkCreateBodyRefMax = 100

export const FileSystemLinkCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLinkCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLinkCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemMoveCreateBodyTypeMax = 100

export const fileSystemMoveCreateBodyRefMax = 100

export const FileSystemMoveCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemMoveCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemMoveCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Get count of all files in a folder.
 */
export const fileSystemCountByPathCreateBodyTypeMax = 100

export const fileSystemCountByPathCreateBodyRefMax = 100

export const FileSystemCountByPathCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemCountByPathCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemCountByPathCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemLogViewCreateBodyTypeMax = 100

export const fileSystemLogViewCreateBodyRefMax = 100

export const FileSystemLogViewCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemLogViewCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemLogViewCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

export const fileSystemUndoDeleteCreateBodyTypeMax = 100

export const fileSystemUndoDeleteCreateBodyRefMax = 100

export const FileSystemUndoDeleteCreateBody = /* @__PURE__ */ zod.object({
    path: zod.string(),
    type: zod.string().max(fileSystemUndoDeleteCreateBodyTypeMax).optional(),
    ref: zod.string().max(fileSystemUndoDeleteCreateBodyRefMax).nullish(),
    href: zod.string().nullish(),
    meta: zod.unknown().nullish(),
    shortcut: zod.boolean().nullish(),
})

/**
 * Create a new password for the sharing configuration.
 */
export const InsightsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const InsightsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const projectSecretApiKeysCreateBodyLabelMax = 40

export const ProjectSecretApiKeysCreateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysCreateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysUpdateBodyLabelMax),
    scopes: zod.array(zod.string()),
})

export const projectSecretApiKeysPartialUpdateBodyLabelMax = 40

export const ProjectSecretApiKeysPartialUpdateBody = /* @__PURE__ */ zod.object({
    label: zod.string().max(projectSecretApiKeysPartialUpdateBodyLabelMax).optional(),
    scopes: zod.array(zod.string()).optional(),
})

export const PropertyDefinitionsUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

export const PropertyDefinitionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        description: zod.string().nullish(),
        tags: zod.array(zod.unknown()).optional(),
        property_type: zod
            .union([
                zod
                    .enum(['DateTime', 'String', 'Numeric', 'Boolean', 'Duration'])
                    .describe(
                        '* `DateTime` - DateTime\n* `String` - String\n* `Numeric` - Numeric\n* `Boolean` - Boolean\n* `Duration` - Duration'
                    ),
                zod.enum(['']),
                zod.literal(null),
            ])
            .nullish(),
        verified: zod.boolean().optional(),
        hidden: zod.boolean().nullish(),
    })
    .describe('Serializer mixin that handles tags for objects.')

/**
 * Bulk update tags on multiple objects.

Accepts:
- {"ids": [...], "action": "add"|"remove"|"set", "tags": ["tag1", "tag2"]}

Actions:
- "add": Add tags to existing tags on each object
- "remove": Remove specific tags from each object
- "set": Replace all tags on each object with the provided list
 */
export const propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax = 500

export const PropertyDefinitionsBulkUpdateTagsCreateBody = /* @__PURE__ */ zod.object({
    ids: zod
        .array(zod.number())
        .max(propertyDefinitionsBulkUpdateTagsCreateBodyIdsMax)
        .describe('List of object IDs to update tags on.'),
    action: zod
        .enum(['add', 'remove', 'set'])
        .describe('* `add` - add\n* `remove` - remove\n* `set` - set')
        .describe(
            "'add' merges with existing tags, 'remove' deletes specific tags, 'set' replaces all tags.\n\n* `add` - add\n* `remove` - remove\n* `set` - set"
        ),
    tags: zod.array(zod.string()).describe('Tag names to add, remove, or set.'),
})

/**
 * Create a new password for the sharing configuration.
 */
export const SessionRecordingsSharingPasswordsCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const SessionRecordingsSharingRefreshCreateBody = /* @__PURE__ */ zod.object({
    enabled: zod.boolean().optional(),
    settings: zod.unknown().nullish(),
    password_required: zod.boolean().optional(),
})

export const subscriptionsCreateBodyIntervalMin = -2147483648
export const subscriptionsCreateBodyIntervalMax = 2147483647

export const subscriptionsCreateBodyBysetposMin = -2147483648
export const subscriptionsCreateBodyBysetposMax = 2147483647

export const subscriptionsCreateBodyCountMin = -2147483648
export const subscriptionsCreateBodyCountMax = 2147483647

export const subscriptionsCreateBodyTitleMax = 100

export const subscriptionsCreateBodySummaryPromptGuideMax = 500

export const SubscriptionsCreateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsCreateBodyIntervalMin)
            .max(subscriptionsCreateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsCreateBodyBysetposMin)
            .max(subscriptionsCreateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsCreateBodyCountMin)
            .max(subscriptionsCreateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsCreateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsCreateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsUpdateBodyIntervalMin = -2147483648
export const subscriptionsUpdateBodyIntervalMax = 2147483647

export const subscriptionsUpdateBodyBysetposMin = -2147483648
export const subscriptionsUpdateBodyBysetposMax = 2147483647

export const subscriptionsUpdateBodyCountMin = -2147483648
export const subscriptionsUpdateBodyCountMax = 2147483647

export const subscriptionsUpdateBodyTitleMax = 100

export const subscriptionsUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsUpdateBodyIntervalMin)
            .max(subscriptionsUpdateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsUpdateBodyBysetposMin)
            .max(subscriptionsUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsUpdateBodyCountMin)
            .max(subscriptionsUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsUpdateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

export const subscriptionsPartialUpdateBodyIntervalMin = -2147483648
export const subscriptionsPartialUpdateBodyIntervalMax = 2147483647

export const subscriptionsPartialUpdateBodyBysetposMin = -2147483648
export const subscriptionsPartialUpdateBodyBysetposMax = 2147483647

export const subscriptionsPartialUpdateBodyCountMin = -2147483648
export const subscriptionsPartialUpdateBodyCountMax = 2147483647

export const subscriptionsPartialUpdateBodyTitleMax = 100

export const subscriptionsPartialUpdateBodySummaryPromptGuideMax = 500

export const SubscriptionsPartialUpdateBody = /* @__PURE__ */ zod
    .object({
        dashboard: zod
            .number()
            .nullish()
            .describe('Dashboard ID to subscribe to (mutually exclusive with insight on create).'),
        insight: zod
            .number()
            .nullish()
            .describe('Insight ID to subscribe to (mutually exclusive with dashboard on create).'),
        dashboard_export_insights: zod
            .array(zod.number())
            .optional()
            .describe(
                'List of insight IDs from the dashboard to include. Required for dashboard subscriptions, max 6.'
            ),
        target_type: zod
            .enum(['email', 'slack', 'webhook'])
            .describe('* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook')
            .optional()
            .describe(
                'Delivery channel: email, slack, or webhook.\n\n* `email` - Email\n* `slack` - Slack\n* `webhook` - Webhook'
            ),
        target_value: zod
            .string()
            .optional()
            .describe(
                'Recipient(s): comma-separated email addresses for email, Slack channel name/ID for slack, or full URL for webhook.'
            ),
        frequency: zod
            .enum(['daily', 'weekly', 'monthly', 'yearly'])
            .describe('* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly')
            .optional()
            .describe(
                'How often to deliver: daily, weekly, monthly, or yearly.\n\n* `daily` - Daily\n* `weekly` - Weekly\n* `monthly` - Monthly\n* `yearly` - Yearly'
            ),
        interval: zod
            .number()
            .min(subscriptionsPartialUpdateBodyIntervalMin)
            .max(subscriptionsPartialUpdateBodyIntervalMax)
            .optional()
            .describe('Interval multiplier (e.g. 2 with weekly frequency means every 2 weeks). Default 1.'),
        byweekday: zod
            .array(
                zod
                    .enum(['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'])
                    .describe(
                        '* `monday` - Monday\n* `tuesday` - Tuesday\n* `wednesday` - Wednesday\n* `thursday` - Thursday\n* `friday` - Friday\n* `saturday` - Saturday\n* `sunday` - Sunday'
                    )
            )
            .nullish()
            .describe(
                'Days of week for weekly subscriptions: monday, tuesday, wednesday, thursday, friday, saturday, sunday.'
            ),
        bysetpos: zod
            .number()
            .min(subscriptionsPartialUpdateBodyBysetposMin)
            .max(subscriptionsPartialUpdateBodyBysetposMax)
            .nullish()
            .describe('Position within byweekday set for monthly frequency (e.g. 1 for first, -1 for last).'),
        count: zod
            .number()
            .min(subscriptionsPartialUpdateBodyCountMin)
            .max(subscriptionsPartialUpdateBodyCountMax)
            .nullish()
            .describe('Total number of deliveries before the subscription stops. Null for unlimited.'),
        start_date: zod.iso.datetime({}).optional().describe('When to start delivering (ISO 8601 datetime).'),
        until_date: zod.iso
            .datetime({})
            .nullish()
            .describe('When to stop delivering (ISO 8601 datetime). Null for indefinite.'),
        deleted: zod.boolean().optional().describe('Set to true to soft-delete. Subscriptions cannot be hard-deleted.'),
        title: zod
            .string()
            .max(subscriptionsPartialUpdateBodyTitleMax)
            .nullish()
            .describe('Human-readable name for this subscription.'),
        integration_id: zod
            .number()
            .nullish()
            .describe('ID of a connected Slack integration. Required when target_type is slack.'),
        invite_message: zod
            .string()
            .nullish()
            .describe('Optional message included in the invitation email when adding new recipients.'),
        summary_enabled: zod.boolean().optional(),
        summary_prompt_guide: zod.string().max(subscriptionsPartialUpdateBodySummaryPromptGuideMax).optional(),
    })
    .describe('Standard Subscription serializer.')

/**
 * Replace the authenticated user's profile and settings. Pass `@me` as the UUID to update the authenticated user. Prefer the PATCH endpoint for partial updates — PUT requires every writable field to be provided.
 */
export const usersUpdateBodyFirstNameMax = 150

export const usersUpdateBodyLastNameMax = 150

export const usersUpdateBodyEmailMax = 254

export const usersUpdateBodyPasswordMax = 128

export const UsersUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersUpdateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersUpdateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

/**
 * Update one or more of the authenticated user's profile fields or settings.
 */
export const usersPartialUpdateBodyFirstNameMax = 150

export const usersPartialUpdateBodyLastNameMax = 150

export const usersPartialUpdateBodyEmailMax = 254

export const usersPartialUpdateBodyPasswordMax = 128

export const UsersPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersHedgehogConfigPartialUpdateBodyFirstNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyLastNameMax = 150

export const usersHedgehogConfigPartialUpdateBodyEmailMax = 254

export const usersHedgehogConfigPartialUpdateBodyPasswordMax = 128

export const UsersHedgehogConfigPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersHedgehogConfigPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersHedgehogConfigPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersHedgehogConfigPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersScenePersonalisationCreateBodyFirstNameMax = 150

export const usersScenePersonalisationCreateBodyLastNameMax = 150

export const usersScenePersonalisationCreateBodyEmailMax = 254

export const usersScenePersonalisationCreateBodyPasswordMax = 128

export const UsersScenePersonalisationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersScenePersonalisationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersScenePersonalisationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersScenePersonalisationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersScenePersonalisationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

/**
 * Generate new backup codes, invalidating any existing ones
 */
export const usersTwoFactorBackupCodesCreateBodyFirstNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyLastNameMax = 150

export const usersTwoFactorBackupCodesCreateBodyEmailMax = 254

export const usersTwoFactorBackupCodesCreateBodyPasswordMax = 128

export const UsersTwoFactorBackupCodesCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorBackupCodesCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorBackupCodesCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorBackupCodesCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

/**
 * Disable 2FA and remove all related devices
 */
export const usersTwoFactorDisableCreateBodyFirstNameMax = 150

export const usersTwoFactorDisableCreateBodyLastNameMax = 150

export const usersTwoFactorDisableCreateBodyEmailMax = 254

export const usersTwoFactorDisableCreateBodyPasswordMax = 128

export const UsersTwoFactorDisableCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorDisableCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorDisableCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorDisableCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorDisableCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersTwoFactorValidateCreateBodyFirstNameMax = 150

export const usersTwoFactorValidateCreateBodyLastNameMax = 150

export const usersTwoFactorValidateCreateBodyEmailMax = 254

export const usersTwoFactorValidateCreateBodyPasswordMax = 128

export const UsersTwoFactorValidateCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersTwoFactorValidateCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersTwoFactorValidateCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersTwoFactorValidateCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersTwoFactorValidateCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersValidate2faCreateBodyFirstNameMax = 150

export const usersValidate2faCreateBodyLastNameMax = 150

export const usersValidate2faCreateBodyEmailMax = 254

export const usersValidate2faCreateBodyPasswordMax = 128

export const UsersValidate2faCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersValidate2faCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersValidate2faCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersValidate2faCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersValidate2faCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax = 150

export const usersCancelEmailChangeRequestPartialUpdateBodyEmailMax = 254

export const usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax = 128

export const UsersCancelEmailChangeRequestPartialUpdateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyLastNameMax).optional(),
    email: zod.email().max(usersCancelEmailChangeRequestPartialUpdateBodyEmailMax).optional(),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersCancelEmailChangeRequestPartialUpdateBodyPasswordMax).optional(),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersRequestEmailVerificationCreateBodyFirstNameMax = 150

export const usersRequestEmailVerificationCreateBodyLastNameMax = 150

export const usersRequestEmailVerificationCreateBodyEmailMax = 254

export const usersRequestEmailVerificationCreateBodyPasswordMax = 128

export const UsersRequestEmailVerificationCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersRequestEmailVerificationCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersRequestEmailVerificationCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersRequestEmailVerificationCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersRequestEmailVerificationCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})

export const usersVerifyEmailCreateBodyFirstNameMax = 150

export const usersVerifyEmailCreateBodyLastNameMax = 150

export const usersVerifyEmailCreateBodyEmailMax = 254

export const usersVerifyEmailCreateBodyPasswordMax = 128

export const UsersVerifyEmailCreateBody = /* @__PURE__ */ zod.object({
    first_name: zod.string().max(usersVerifyEmailCreateBodyFirstNameMax).optional(),
    last_name: zod.string().max(usersVerifyEmailCreateBodyLastNameMax).optional(),
    email: zod.email().max(usersVerifyEmailCreateBodyEmailMax),
    notification_settings: zod
        .record(zod.string(), zod.unknown())
        .optional()
        .describe(
            'Map of notification preferences. Keys include `plugin_disabled`, `all_weekly_report_disabled`, `project_weekly_digest_disabled`, `error_tracking_weekly_digest_project_enabled`, `web_analytics_weekly_digest_project_enabled`, `organization_member_join_email_disabled`, `data_pipeline_error_threshold` (number between 0.0 and 1.0), and other per-topic switches. Values are either booleans, or (for per-project/per-resource keys) a map of IDs to booleans. Only the keys you send are updated — other preferences stay as-is.'
        ),
    anonymize_data: zod
        .boolean()
        .nullish()
        .describe('Whether PostHog should anonymize events captured for this user when identified.'),
    allow_impersonation: zod.boolean().nullish(),
    toolbar_mode: zod
        .union([
            zod.enum(['disabled', 'toolbar']).describe('* `disabled` - disabled\n* `toolbar` - toolbar'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    is_staff: zod.boolean().optional().describe('Designates whether the user can log into this admin site.'),
    set_current_organization: zod.string().optional(),
    set_current_team: zod.string().optional(),
    password: zod.string().max(usersVerifyEmailCreateBodyPasswordMax),
    current_password: zod
        .string()
        .optional()
        .describe(
            "The user's current password. Required when changing `password` if the user already has a usable password set."
        ),
    events_column_config: zod.unknown().optional(),
    has_seen_product_intro_for: zod.unknown().nullish(),
    theme_mode: zod
        .union([
            zod.enum(['light', 'dark', 'system']).describe('* `light` - Light\n* `dark` - Dark\n* `system` - System'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    hedgehog_config: zod.unknown().nullish(),
    allow_sidebar_suggestions: zod.boolean().nullish(),
    shortcut_position: zod
        .union([
            zod
                .enum(['above', 'below', 'hidden'])
                .describe('* `above` - Above\n* `below` - Below\n* `hidden` - Hidden'),
            zod.enum(['']),
            zod.literal(null),
        ])
        .nullish(),
    role_at_organization: zod
        .enum(['engineering', 'data', 'product', 'founder', 'leadership', 'marketing', 'sales', 'other'])
        .optional()
        .describe(
            '* `engineering` - Engineering\n* `data` - Data\n* `product` - Product Management\n* `founder` - Founder\n* `leadership` - Leadership\n* `marketing` - Marketing\n* `sales` - Sales / Success\n* `other` - Other'
        ),
    passkeys_enabled_for_2fa: zod
        .boolean()
        .nullish()
        .describe(
            'Whether passkeys are enabled for 2FA authentication. Users can disable this to use only TOTP for 2FA while keeping passkeys for login.'
        ),
})
