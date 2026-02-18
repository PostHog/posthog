/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `events` - Events
 * `persons` - Persons
 * `sessions` - Sessions
 */
export type ModelEnumApi = (typeof ModelEnumApi)[keyof typeof ModelEnumApi]

export const ModelEnumApi = {
    Events: 'events',
    Persons: 'persons',
    Sessions: 'sessions',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

export type NullEnumApi = (typeof NullEnumApi)[keyof typeof NullEnumApi]

export const NullEnumApi = {} as const

/**
 * * `S3` - S3
 * `Snowflake` - Snowflake
 * `Postgres` - Postgres
 * `Redshift` - Redshift
 * `BigQuery` - Bigquery
 * `Databricks` - Databricks
 * `AzureBlob` - Azure Blob
 * `Workflows` - Workflows
 * `HTTP` - Http
 * `NoOp` - Noop
 */
export type BatchExportDestinationTypeEnumApi =
    (typeof BatchExportDestinationTypeEnumApi)[keyof typeof BatchExportDestinationTypeEnumApi]

export const BatchExportDestinationTypeEnumApi = {
    S3: 'S3',
    Snowflake: 'Snowflake',
    Postgres: 'Postgres',
    Redshift: 'Redshift',
    BigQuery: 'BigQuery',
    Databricks: 'Databricks',
    AzureBlob: 'AzureBlob',
    Workflows: 'Workflows',
    Http: 'HTTP',
    NoOp: 'NoOp',
} as const

/**
 * Serializer for an BatchExportDestination model.
 */
export interface BatchExportDestinationApi {
    /** A choice of supported BatchExportDestination types.

* `S3` - S3
* `Snowflake` - Snowflake
* `Postgres` - Postgres
* `Redshift` - Redshift
* `BigQuery` - Bigquery
* `Databricks` - Databricks
* `AzureBlob` - Azure Blob
* `Workflows` - Workflows
* `HTTP` - Http
* `NoOp` - Noop */
    type: BatchExportDestinationTypeEnumApi
    /** A JSON field to store all configuration parameters required to access a BatchExportDestination. */
    config?: unknown
    /**
     * The integration for this destination.
     * @nullable
     */
    integration?: number | null
    /** @nullable */
    integration_id?: number | null
}

/**
 * * `hour` - hour
 * `day` - day
 * `week` - week
 * `every 5 minutes` - every 5 minutes
 */
export type IntervalEnumApi = (typeof IntervalEnumApi)[keyof typeof IntervalEnumApi]

export const IntervalEnumApi = {
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Every5Minutes: 'every 5 minutes',
} as const

/**
 * * `Cancelled` - Cancelled
 * `Completed` - Completed
 * `ContinuedAsNew` - Continued As New
 * `Failed` - Failed
 * `FailedRetryable` - Failed Retryable
 * `FailedBilling` - Failed Billing
 * `Terminated` - Terminated
 * `TimedOut` - Timedout
 * `Running` - Running
 * `Starting` - Starting
 */
export type BatchExportRunStatusEnumApi = (typeof BatchExportRunStatusEnumApi)[keyof typeof BatchExportRunStatusEnumApi]

export const BatchExportRunStatusEnumApi = {
    Cancelled: 'Cancelled',
    Completed: 'Completed',
    ContinuedAsNew: 'ContinuedAsNew',
    Failed: 'Failed',
    FailedRetryable: 'FailedRetryable',
    FailedBilling: 'FailedBilling',
    Terminated: 'Terminated',
    TimedOut: 'TimedOut',
    Running: 'Running',
    Starting: 'Starting',
} as const

/**
 * Serializer for a BatchExportRun model.
 */
export interface BatchExportRunApi {
    readonly id: string
    /** The status of this run.

* `Cancelled` - Cancelled
* `Completed` - Completed
* `ContinuedAsNew` - Continued As New
* `Failed` - Failed
* `FailedRetryable` - Failed Retryable
* `FailedBilling` - Failed Billing
* `Terminated` - Terminated
* `TimedOut` - Timedout
* `Running` - Running
* `Starting` - Starting */
    status: BatchExportRunStatusEnumApi
    /**
     * The number of records that have been exported.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    records_completed?: number | null
    /**
     * The latest error that occurred during this run.
     * @nullable
     */
    latest_error?: string | null
    /**
     * The start of the data interval.
     * @nullable
     */
    data_interval_start?: string | null
    /** The end of the data interval. */
    data_interval_end: string
    /**
     * An opaque cursor that may be used to resume.
     * @nullable
     */
    cursor?: string | null
    /** The timestamp at which this BatchExportRun was created. */
    readonly created_at: string
    /**
     * The timestamp at which this BatchExportRun finished, successfully or not.
     * @nullable
     */
    finished_at?: string | null
    /** The timestamp at which this BatchExportRun was last updated. */
    readonly last_updated_at: string
    /**
     * The total count of records that should be exported in this BatchExportRun.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    records_total_count?: number | null
    /**
     * The number of bytes that have been exported in this BatchExportRun.
     * @minimum -9223372036854776000
     * @maximum 9223372036854776000
     * @nullable
     */
    bytes_exported?: number | null
    /** The BatchExport this run belongs to. */
    readonly batch_export: string
    /**
     * The backfill this run belongs to.
     * @nullable
     */
    backfill?: string | null
}

/**
 * * `Africa/Abidjan` - Africa/Abidjan
 * `Africa/Accra` - Africa/Accra
 * `Africa/Addis_Ababa` - Africa/Addis_Ababa
 * `Africa/Algiers` - Africa/Algiers
 * `Africa/Asmara` - Africa/Asmara
 * `Africa/Asmera` - Africa/Asmera
 * `Africa/Bamako` - Africa/Bamako
 * `Africa/Bangui` - Africa/Bangui
 * `Africa/Banjul` - Africa/Banjul
 * `Africa/Bissau` - Africa/Bissau
 * `Africa/Blantyre` - Africa/Blantyre
 * `Africa/Brazzaville` - Africa/Brazzaville
 * `Africa/Bujumbura` - Africa/Bujumbura
 * `Africa/Cairo` - Africa/Cairo
 * `Africa/Casablanca` - Africa/Casablanca
 * `Africa/Ceuta` - Africa/Ceuta
 * `Africa/Conakry` - Africa/Conakry
 * `Africa/Dakar` - Africa/Dakar
 * `Africa/Dar_es_Salaam` - Africa/Dar_es_Salaam
 * `Africa/Djibouti` - Africa/Djibouti
 * `Africa/Douala` - Africa/Douala
 * `Africa/El_Aaiun` - Africa/El_Aaiun
 * `Africa/Freetown` - Africa/Freetown
 * `Africa/Gaborone` - Africa/Gaborone
 * `Africa/Harare` - Africa/Harare
 * `Africa/Johannesburg` - Africa/Johannesburg
 * `Africa/Juba` - Africa/Juba
 * `Africa/Kampala` - Africa/Kampala
 * `Africa/Khartoum` - Africa/Khartoum
 * `Africa/Kigali` - Africa/Kigali
 * `Africa/Kinshasa` - Africa/Kinshasa
 * `Africa/Lagos` - Africa/Lagos
 * `Africa/Libreville` - Africa/Libreville
 * `Africa/Lome` - Africa/Lome
 * `Africa/Luanda` - Africa/Luanda
 * `Africa/Lubumbashi` - Africa/Lubumbashi
 * `Africa/Lusaka` - Africa/Lusaka
 * `Africa/Malabo` - Africa/Malabo
 * `Africa/Maputo` - Africa/Maputo
 * `Africa/Maseru` - Africa/Maseru
 * `Africa/Mbabane` - Africa/Mbabane
 * `Africa/Mogadishu` - Africa/Mogadishu
 * `Africa/Monrovia` - Africa/Monrovia
 * `Africa/Nairobi` - Africa/Nairobi
 * `Africa/Ndjamena` - Africa/Ndjamena
 * `Africa/Niamey` - Africa/Niamey
 * `Africa/Nouakchott` - Africa/Nouakchott
 * `Africa/Ouagadougou` - Africa/Ouagadougou
 * `Africa/Porto-Novo` - Africa/Porto-Novo
 * `Africa/Sao_Tome` - Africa/Sao_Tome
 * `Africa/Timbuktu` - Africa/Timbuktu
 * `Africa/Tripoli` - Africa/Tripoli
 * `Africa/Tunis` - Africa/Tunis
 * `Africa/Windhoek` - Africa/Windhoek
 * `America/Adak` - America/Adak
 * `America/Anchorage` - America/Anchorage
 * `America/Anguilla` - America/Anguilla
 * `America/Antigua` - America/Antigua
 * `America/Araguaina` - America/Araguaina
 * `America/Argentina/Buenos_Aires` - America/Argentina/Buenos_Aires
 * `America/Argentina/Catamarca` - America/Argentina/Catamarca
 * `America/Argentina/ComodRivadavia` - America/Argentina/ComodRivadavia
 * `America/Argentina/Cordoba` - America/Argentina/Cordoba
 * `America/Argentina/Jujuy` - America/Argentina/Jujuy
 * `America/Argentina/La_Rioja` - America/Argentina/La_Rioja
 * `America/Argentina/Mendoza` - America/Argentina/Mendoza
 * `America/Argentina/Rio_Gallegos` - America/Argentina/Rio_Gallegos
 * `America/Argentina/Salta` - America/Argentina/Salta
 * `America/Argentina/San_Juan` - America/Argentina/San_Juan
 * `America/Argentina/San_Luis` - America/Argentina/San_Luis
 * `America/Argentina/Tucuman` - America/Argentina/Tucuman
 * `America/Argentina/Ushuaia` - America/Argentina/Ushuaia
 * `America/Aruba` - America/Aruba
 * `America/Asuncion` - America/Asuncion
 * `America/Atikokan` - America/Atikokan
 * `America/Atka` - America/Atka
 * `America/Bahia` - America/Bahia
 * `America/Bahia_Banderas` - America/Bahia_Banderas
 * `America/Barbados` - America/Barbados
 * `America/Belem` - America/Belem
 * `America/Belize` - America/Belize
 * `America/Blanc-Sablon` - America/Blanc-Sablon
 * `America/Boa_Vista` - America/Boa_Vista
 * `America/Bogota` - America/Bogota
 * `America/Boise` - America/Boise
 * `America/Buenos_Aires` - America/Buenos_Aires
 * `America/Cambridge_Bay` - America/Cambridge_Bay
 * `America/Campo_Grande` - America/Campo_Grande
 * `America/Cancun` - America/Cancun
 * `America/Caracas` - America/Caracas
 * `America/Catamarca` - America/Catamarca
 * `America/Cayenne` - America/Cayenne
 * `America/Cayman` - America/Cayman
 * `America/Chicago` - America/Chicago
 * `America/Chihuahua` - America/Chihuahua
 * `America/Ciudad_Juarez` - America/Ciudad_Juarez
 * `America/Coral_Harbour` - America/Coral_Harbour
 * `America/Cordoba` - America/Cordoba
 * `America/Costa_Rica` - America/Costa_Rica
 * `America/Creston` - America/Creston
 * `America/Cuiaba` - America/Cuiaba
 * `America/Curacao` - America/Curacao
 * `America/Danmarkshavn` - America/Danmarkshavn
 * `America/Dawson` - America/Dawson
 * `America/Dawson_Creek` - America/Dawson_Creek
 * `America/Denver` - America/Denver
 * `America/Detroit` - America/Detroit
 * `America/Dominica` - America/Dominica
 * `America/Edmonton` - America/Edmonton
 * `America/Eirunepe` - America/Eirunepe
 * `America/El_Salvador` - America/El_Salvador
 * `America/Ensenada` - America/Ensenada
 * `America/Fort_Nelson` - America/Fort_Nelson
 * `America/Fort_Wayne` - America/Fort_Wayne
 * `America/Fortaleza` - America/Fortaleza
 * `America/Glace_Bay` - America/Glace_Bay
 * `America/Godthab` - America/Godthab
 * `America/Goose_Bay` - America/Goose_Bay
 * `America/Grand_Turk` - America/Grand_Turk
 * `America/Grenada` - America/Grenada
 * `America/Guadeloupe` - America/Guadeloupe
 * `America/Guatemala` - America/Guatemala
 * `America/Guayaquil` - America/Guayaquil
 * `America/Guyana` - America/Guyana
 * `America/Halifax` - America/Halifax
 * `America/Havana` - America/Havana
 * `America/Hermosillo` - America/Hermosillo
 * `America/Indiana/Indianapolis` - America/Indiana/Indianapolis
 * `America/Indiana/Knox` - America/Indiana/Knox
 * `America/Indiana/Marengo` - America/Indiana/Marengo
 * `America/Indiana/Petersburg` - America/Indiana/Petersburg
 * `America/Indiana/Tell_City` - America/Indiana/Tell_City
 * `America/Indiana/Vevay` - America/Indiana/Vevay
 * `America/Indiana/Vincennes` - America/Indiana/Vincennes
 * `America/Indiana/Winamac` - America/Indiana/Winamac
 * `America/Indianapolis` - America/Indianapolis
 * `America/Inuvik` - America/Inuvik
 * `America/Iqaluit` - America/Iqaluit
 * `America/Jamaica` - America/Jamaica
 * `America/Jujuy` - America/Jujuy
 * `America/Juneau` - America/Juneau
 * `America/Kentucky/Louisville` - America/Kentucky/Louisville
 * `America/Kentucky/Monticello` - America/Kentucky/Monticello
 * `America/Knox_IN` - America/Knox_IN
 * `America/Kralendijk` - America/Kralendijk
 * `America/La_Paz` - America/La_Paz
 * `America/Lima` - America/Lima
 * `America/Los_Angeles` - America/Los_Angeles
 * `America/Louisville` - America/Louisville
 * `America/Lower_Princes` - America/Lower_Princes
 * `America/Maceio` - America/Maceio
 * `America/Managua` - America/Managua
 * `America/Manaus` - America/Manaus
 * `America/Marigot` - America/Marigot
 * `America/Martinique` - America/Martinique
 * `America/Matamoros` - America/Matamoros
 * `America/Mazatlan` - America/Mazatlan
 * `America/Mendoza` - America/Mendoza
 * `America/Menominee` - America/Menominee
 * `America/Merida` - America/Merida
 * `America/Metlakatla` - America/Metlakatla
 * `America/Mexico_City` - America/Mexico_City
 * `America/Miquelon` - America/Miquelon
 * `America/Moncton` - America/Moncton
 * `America/Monterrey` - America/Monterrey
 * `America/Montevideo` - America/Montevideo
 * `America/Montreal` - America/Montreal
 * `America/Montserrat` - America/Montserrat
 * `America/Nassau` - America/Nassau
 * `America/New_York` - America/New_York
 * `America/Nipigon` - America/Nipigon
 * `America/Nome` - America/Nome
 * `America/Noronha` - America/Noronha
 * `America/North_Dakota/Beulah` - America/North_Dakota/Beulah
 * `America/North_Dakota/Center` - America/North_Dakota/Center
 * `America/North_Dakota/New_Salem` - America/North_Dakota/New_Salem
 * `America/Nuuk` - America/Nuuk
 * `America/Ojinaga` - America/Ojinaga
 * `America/Panama` - America/Panama
 * `America/Pangnirtung` - America/Pangnirtung
 * `America/Paramaribo` - America/Paramaribo
 * `America/Phoenix` - America/Phoenix
 * `America/Port-au-Prince` - America/Port-au-Prince
 * `America/Port_of_Spain` - America/Port_of_Spain
 * `America/Porto_Acre` - America/Porto_Acre
 * `America/Porto_Velho` - America/Porto_Velho
 * `America/Puerto_Rico` - America/Puerto_Rico
 * `America/Punta_Arenas` - America/Punta_Arenas
 * `America/Rainy_River` - America/Rainy_River
 * `America/Rankin_Inlet` - America/Rankin_Inlet
 * `America/Recife` - America/Recife
 * `America/Regina` - America/Regina
 * `America/Resolute` - America/Resolute
 * `America/Rio_Branco` - America/Rio_Branco
 * `America/Rosario` - America/Rosario
 * `America/Santa_Isabel` - America/Santa_Isabel
 * `America/Santarem` - America/Santarem
 * `America/Santiago` - America/Santiago
 * `America/Santo_Domingo` - America/Santo_Domingo
 * `America/Sao_Paulo` - America/Sao_Paulo
 * `America/Scoresbysund` - America/Scoresbysund
 * `America/Shiprock` - America/Shiprock
 * `America/Sitka` - America/Sitka
 * `America/St_Barthelemy` - America/St_Barthelemy
 * `America/St_Johns` - America/St_Johns
 * `America/St_Kitts` - America/St_Kitts
 * `America/St_Lucia` - America/St_Lucia
 * `America/St_Thomas` - America/St_Thomas
 * `America/St_Vincent` - America/St_Vincent
 * `America/Swift_Current` - America/Swift_Current
 * `America/Tegucigalpa` - America/Tegucigalpa
 * `America/Thule` - America/Thule
 * `America/Thunder_Bay` - America/Thunder_Bay
 * `America/Tijuana` - America/Tijuana
 * `America/Toronto` - America/Toronto
 * `America/Tortola` - America/Tortola
 * `America/Vancouver` - America/Vancouver
 * `America/Virgin` - America/Virgin
 * `America/Whitehorse` - America/Whitehorse
 * `America/Winnipeg` - America/Winnipeg
 * `America/Yakutat` - America/Yakutat
 * `America/Yellowknife` - America/Yellowknife
 * `Antarctica/Casey` - Antarctica/Casey
 * `Antarctica/Davis` - Antarctica/Davis
 * `Antarctica/DumontDUrville` - Antarctica/DumontDUrville
 * `Antarctica/Macquarie` - Antarctica/Macquarie
 * `Antarctica/Mawson` - Antarctica/Mawson
 * `Antarctica/McMurdo` - Antarctica/McMurdo
 * `Antarctica/Palmer` - Antarctica/Palmer
 * `Antarctica/Rothera` - Antarctica/Rothera
 * `Antarctica/South_Pole` - Antarctica/South_Pole
 * `Antarctica/Syowa` - Antarctica/Syowa
 * `Antarctica/Troll` - Antarctica/Troll
 * `Antarctica/Vostok` - Antarctica/Vostok
 * `Arctic/Longyearbyen` - Arctic/Longyearbyen
 * `Asia/Aden` - Asia/Aden
 * `Asia/Almaty` - Asia/Almaty
 * `Asia/Amman` - Asia/Amman
 * `Asia/Anadyr` - Asia/Anadyr
 * `Asia/Aqtau` - Asia/Aqtau
 * `Asia/Aqtobe` - Asia/Aqtobe
 * `Asia/Ashgabat` - Asia/Ashgabat
 * `Asia/Ashkhabad` - Asia/Ashkhabad
 * `Asia/Atyrau` - Asia/Atyrau
 * `Asia/Baghdad` - Asia/Baghdad
 * `Asia/Bahrain` - Asia/Bahrain
 * `Asia/Baku` - Asia/Baku
 * `Asia/Bangkok` - Asia/Bangkok
 * `Asia/Barnaul` - Asia/Barnaul
 * `Asia/Beirut` - Asia/Beirut
 * `Asia/Bishkek` - Asia/Bishkek
 * `Asia/Brunei` - Asia/Brunei
 * `Asia/Calcutta` - Asia/Calcutta
 * `Asia/Chita` - Asia/Chita
 * `Asia/Choibalsan` - Asia/Choibalsan
 * `Asia/Chongqing` - Asia/Chongqing
 * `Asia/Chungking` - Asia/Chungking
 * `Asia/Colombo` - Asia/Colombo
 * `Asia/Dacca` - Asia/Dacca
 * `Asia/Damascus` - Asia/Damascus
 * `Asia/Dhaka` - Asia/Dhaka
 * `Asia/Dili` - Asia/Dili
 * `Asia/Dubai` - Asia/Dubai
 * `Asia/Dushanbe` - Asia/Dushanbe
 * `Asia/Famagusta` - Asia/Famagusta
 * `Asia/Gaza` - Asia/Gaza
 * `Asia/Harbin` - Asia/Harbin
 * `Asia/Hebron` - Asia/Hebron
 * `Asia/Ho_Chi_Minh` - Asia/Ho_Chi_Minh
 * `Asia/Hong_Kong` - Asia/Hong_Kong
 * `Asia/Hovd` - Asia/Hovd
 * `Asia/Irkutsk` - Asia/Irkutsk
 * `Asia/Istanbul` - Asia/Istanbul
 * `Asia/Jakarta` - Asia/Jakarta
 * `Asia/Jayapura` - Asia/Jayapura
 * `Asia/Jerusalem` - Asia/Jerusalem
 * `Asia/Kabul` - Asia/Kabul
 * `Asia/Kamchatka` - Asia/Kamchatka
 * `Asia/Karachi` - Asia/Karachi
 * `Asia/Kashgar` - Asia/Kashgar
 * `Asia/Kathmandu` - Asia/Kathmandu
 * `Asia/Katmandu` - Asia/Katmandu
 * `Asia/Khandyga` - Asia/Khandyga
 * `Asia/Kolkata` - Asia/Kolkata
 * `Asia/Krasnoyarsk` - Asia/Krasnoyarsk
 * `Asia/Kuala_Lumpur` - Asia/Kuala_Lumpur
 * `Asia/Kuching` - Asia/Kuching
 * `Asia/Kuwait` - Asia/Kuwait
 * `Asia/Macao` - Asia/Macao
 * `Asia/Macau` - Asia/Macau
 * `Asia/Magadan` - Asia/Magadan
 * `Asia/Makassar` - Asia/Makassar
 * `Asia/Manila` - Asia/Manila
 * `Asia/Muscat` - Asia/Muscat
 * `Asia/Nicosia` - Asia/Nicosia
 * `Asia/Novokuznetsk` - Asia/Novokuznetsk
 * `Asia/Novosibirsk` - Asia/Novosibirsk
 * `Asia/Omsk` - Asia/Omsk
 * `Asia/Oral` - Asia/Oral
 * `Asia/Phnom_Penh` - Asia/Phnom_Penh
 * `Asia/Pontianak` - Asia/Pontianak
 * `Asia/Pyongyang` - Asia/Pyongyang
 * `Asia/Qatar` - Asia/Qatar
 * `Asia/Qostanay` - Asia/Qostanay
 * `Asia/Qyzylorda` - Asia/Qyzylorda
 * `Asia/Rangoon` - Asia/Rangoon
 * `Asia/Riyadh` - Asia/Riyadh
 * `Asia/Saigon` - Asia/Saigon
 * `Asia/Sakhalin` - Asia/Sakhalin
 * `Asia/Samarkand` - Asia/Samarkand
 * `Asia/Seoul` - Asia/Seoul
 * `Asia/Shanghai` - Asia/Shanghai
 * `Asia/Singapore` - Asia/Singapore
 * `Asia/Srednekolymsk` - Asia/Srednekolymsk
 * `Asia/Taipei` - Asia/Taipei
 * `Asia/Tashkent` - Asia/Tashkent
 * `Asia/Tbilisi` - Asia/Tbilisi
 * `Asia/Tehran` - Asia/Tehran
 * `Asia/Tel_Aviv` - Asia/Tel_Aviv
 * `Asia/Thimbu` - Asia/Thimbu
 * `Asia/Thimphu` - Asia/Thimphu
 * `Asia/Tokyo` - Asia/Tokyo
 * `Asia/Tomsk` - Asia/Tomsk
 * `Asia/Ujung_Pandang` - Asia/Ujung_Pandang
 * `Asia/Ulaanbaatar` - Asia/Ulaanbaatar
 * `Asia/Ulan_Bator` - Asia/Ulan_Bator
 * `Asia/Urumqi` - Asia/Urumqi
 * `Asia/Ust-Nera` - Asia/Ust-Nera
 * `Asia/Vientiane` - Asia/Vientiane
 * `Asia/Vladivostok` - Asia/Vladivostok
 * `Asia/Yakutsk` - Asia/Yakutsk
 * `Asia/Yangon` - Asia/Yangon
 * `Asia/Yekaterinburg` - Asia/Yekaterinburg
 * `Asia/Yerevan` - Asia/Yerevan
 * `Atlantic/Azores` - Atlantic/Azores
 * `Atlantic/Bermuda` - Atlantic/Bermuda
 * `Atlantic/Canary` - Atlantic/Canary
 * `Atlantic/Cape_Verde` - Atlantic/Cape_Verde
 * `Atlantic/Faeroe` - Atlantic/Faeroe
 * `Atlantic/Faroe` - Atlantic/Faroe
 * `Atlantic/Jan_Mayen` - Atlantic/Jan_Mayen
 * `Atlantic/Madeira` - Atlantic/Madeira
 * `Atlantic/Reykjavik` - Atlantic/Reykjavik
 * `Atlantic/South_Georgia` - Atlantic/South_Georgia
 * `Atlantic/St_Helena` - Atlantic/St_Helena
 * `Atlantic/Stanley` - Atlantic/Stanley
 * `Australia/ACT` - Australia/ACT
 * `Australia/Adelaide` - Australia/Adelaide
 * `Australia/Brisbane` - Australia/Brisbane
 * `Australia/Broken_Hill` - Australia/Broken_Hill
 * `Australia/Canberra` - Australia/Canberra
 * `Australia/Currie` - Australia/Currie
 * `Australia/Darwin` - Australia/Darwin
 * `Australia/Eucla` - Australia/Eucla
 * `Australia/Hobart` - Australia/Hobart
 * `Australia/LHI` - Australia/LHI
 * `Australia/Lindeman` - Australia/Lindeman
 * `Australia/Lord_Howe` - Australia/Lord_Howe
 * `Australia/Melbourne` - Australia/Melbourne
 * `Australia/NSW` - Australia/NSW
 * `Australia/North` - Australia/North
 * `Australia/Perth` - Australia/Perth
 * `Australia/Queensland` - Australia/Queensland
 * `Australia/South` - Australia/South
 * `Australia/Sydney` - Australia/Sydney
 * `Australia/Tasmania` - Australia/Tasmania
 * `Australia/Victoria` - Australia/Victoria
 * `Australia/West` - Australia/West
 * `Australia/Yancowinna` - Australia/Yancowinna
 * `Brazil/Acre` - Brazil/Acre
 * `Brazil/DeNoronha` - Brazil/DeNoronha
 * `Brazil/East` - Brazil/East
 * `Brazil/West` - Brazil/West
 * `CET` - CET
 * `CST6CDT` - CST6CDT
 * `Canada/Atlantic` - Canada/Atlantic
 * `Canada/Central` - Canada/Central
 * `Canada/Eastern` - Canada/Eastern
 * `Canada/Mountain` - Canada/Mountain
 * `Canada/Newfoundland` - Canada/Newfoundland
 * `Canada/Pacific` - Canada/Pacific
 * `Canada/Saskatchewan` - Canada/Saskatchewan
 * `Canada/Yukon` - Canada/Yukon
 * `Chile/Continental` - Chile/Continental
 * `Chile/EasterIsland` - Chile/EasterIsland
 * `Cuba` - Cuba
 * `EET` - EET
 * `EST` - EST
 * `EST5EDT` - EST5EDT
 * `Egypt` - Egypt
 * `Eire` - Eire
 * `Etc/GMT` - Etc/GMT
 * `Etc/GMT+0` - Etc/GMT+0
 * `Etc/GMT+1` - Etc/GMT+1
 * `Etc/GMT+10` - Etc/GMT+10
 * `Etc/GMT+11` - Etc/GMT+11
 * `Etc/GMT+12` - Etc/GMT+12
 * `Etc/GMT+2` - Etc/GMT+2
 * `Etc/GMT+3` - Etc/GMT+3
 * `Etc/GMT+4` - Etc/GMT+4
 * `Etc/GMT+5` - Etc/GMT+5
 * `Etc/GMT+6` - Etc/GMT+6
 * `Etc/GMT+7` - Etc/GMT+7
 * `Etc/GMT+8` - Etc/GMT+8
 * `Etc/GMT+9` - Etc/GMT+9
 * `Etc/GMT-0` - Etc/GMT-0
 * `Etc/GMT-1` - Etc/GMT-1
 * `Etc/GMT-10` - Etc/GMT-10
 * `Etc/GMT-11` - Etc/GMT-11
 * `Etc/GMT-12` - Etc/GMT-12
 * `Etc/GMT-13` - Etc/GMT-13
 * `Etc/GMT-14` - Etc/GMT-14
 * `Etc/GMT-2` - Etc/GMT-2
 * `Etc/GMT-3` - Etc/GMT-3
 * `Etc/GMT-4` - Etc/GMT-4
 * `Etc/GMT-5` - Etc/GMT-5
 * `Etc/GMT-6` - Etc/GMT-6
 * `Etc/GMT-7` - Etc/GMT-7
 * `Etc/GMT-8` - Etc/GMT-8
 * `Etc/GMT-9` - Etc/GMT-9
 * `Etc/GMT0` - Etc/GMT0
 * `Etc/Greenwich` - Etc/Greenwich
 * `Etc/UCT` - Etc/UCT
 * `Etc/UTC` - Etc/UTC
 * `Etc/Universal` - Etc/Universal
 * `Etc/Zulu` - Etc/Zulu
 * `Europe/Amsterdam` - Europe/Amsterdam
 * `Europe/Andorra` - Europe/Andorra
 * `Europe/Astrakhan` - Europe/Astrakhan
 * `Europe/Athens` - Europe/Athens
 * `Europe/Belfast` - Europe/Belfast
 * `Europe/Belgrade` - Europe/Belgrade
 * `Europe/Berlin` - Europe/Berlin
 * `Europe/Bratislava` - Europe/Bratislava
 * `Europe/Brussels` - Europe/Brussels
 * `Europe/Bucharest` - Europe/Bucharest
 * `Europe/Budapest` - Europe/Budapest
 * `Europe/Busingen` - Europe/Busingen
 * `Europe/Chisinau` - Europe/Chisinau
 * `Europe/Copenhagen` - Europe/Copenhagen
 * `Europe/Dublin` - Europe/Dublin
 * `Europe/Gibraltar` - Europe/Gibraltar
 * `Europe/Guernsey` - Europe/Guernsey
 * `Europe/Helsinki` - Europe/Helsinki
 * `Europe/Isle_of_Man` - Europe/Isle_of_Man
 * `Europe/Istanbul` - Europe/Istanbul
 * `Europe/Jersey` - Europe/Jersey
 * `Europe/Kaliningrad` - Europe/Kaliningrad
 * `Europe/Kiev` - Europe/Kiev
 * `Europe/Kirov` - Europe/Kirov
 * `Europe/Kyiv` - Europe/Kyiv
 * `Europe/Lisbon` - Europe/Lisbon
 * `Europe/Ljubljana` - Europe/Ljubljana
 * `Europe/London` - Europe/London
 * `Europe/Luxembourg` - Europe/Luxembourg
 * `Europe/Madrid` - Europe/Madrid
 * `Europe/Malta` - Europe/Malta
 * `Europe/Mariehamn` - Europe/Mariehamn
 * `Europe/Minsk` - Europe/Minsk
 * `Europe/Monaco` - Europe/Monaco
 * `Europe/Moscow` - Europe/Moscow
 * `Europe/Nicosia` - Europe/Nicosia
 * `Europe/Oslo` - Europe/Oslo
 * `Europe/Paris` - Europe/Paris
 * `Europe/Podgorica` - Europe/Podgorica
 * `Europe/Prague` - Europe/Prague
 * `Europe/Riga` - Europe/Riga
 * `Europe/Rome` - Europe/Rome
 * `Europe/Samara` - Europe/Samara
 * `Europe/San_Marino` - Europe/San_Marino
 * `Europe/Sarajevo` - Europe/Sarajevo
 * `Europe/Saratov` - Europe/Saratov
 * `Europe/Simferopol` - Europe/Simferopol
 * `Europe/Skopje` - Europe/Skopje
 * `Europe/Sofia` - Europe/Sofia
 * `Europe/Stockholm` - Europe/Stockholm
 * `Europe/Tallinn` - Europe/Tallinn
 * `Europe/Tirane` - Europe/Tirane
 * `Europe/Tiraspol` - Europe/Tiraspol
 * `Europe/Ulyanovsk` - Europe/Ulyanovsk
 * `Europe/Uzhgorod` - Europe/Uzhgorod
 * `Europe/Vaduz` - Europe/Vaduz
 * `Europe/Vatican` - Europe/Vatican
 * `Europe/Vienna` - Europe/Vienna
 * `Europe/Vilnius` - Europe/Vilnius
 * `Europe/Volgograd` - Europe/Volgograd
 * `Europe/Warsaw` - Europe/Warsaw
 * `Europe/Zagreb` - Europe/Zagreb
 * `Europe/Zaporozhye` - Europe/Zaporozhye
 * `Europe/Zurich` - Europe/Zurich
 * `GB` - GB
 * `GB-Eire` - GB-Eire
 * `GMT` - GMT
 * `GMT+0` - GMT+0
 * `GMT-0` - GMT-0
 * `GMT0` - GMT0
 * `Greenwich` - Greenwich
 * `HST` - HST
 * `Hongkong` - Hongkong
 * `Iceland` - Iceland
 * `Indian/Antananarivo` - Indian/Antananarivo
 * `Indian/Chagos` - Indian/Chagos
 * `Indian/Christmas` - Indian/Christmas
 * `Indian/Cocos` - Indian/Cocos
 * `Indian/Comoro` - Indian/Comoro
 * `Indian/Kerguelen` - Indian/Kerguelen
 * `Indian/Mahe` - Indian/Mahe
 * `Indian/Maldives` - Indian/Maldives
 * `Indian/Mauritius` - Indian/Mauritius
 * `Indian/Mayotte` - Indian/Mayotte
 * `Indian/Reunion` - Indian/Reunion
 * `Iran` - Iran
 * `Israel` - Israel
 * `Jamaica` - Jamaica
 * `Japan` - Japan
 * `Kwajalein` - Kwajalein
 * `Libya` - Libya
 * `MET` - MET
 * `MST` - MST
 * `MST7MDT` - MST7MDT
 * `Mexico/BajaNorte` - Mexico/BajaNorte
 * `Mexico/BajaSur` - Mexico/BajaSur
 * `Mexico/General` - Mexico/General
 * `NZ` - NZ
 * `NZ-CHAT` - NZ-CHAT
 * `Navajo` - Navajo
 * `PRC` - PRC
 * `PST8PDT` - PST8PDT
 * `Pacific/Apia` - Pacific/Apia
 * `Pacific/Auckland` - Pacific/Auckland
 * `Pacific/Bougainville` - Pacific/Bougainville
 * `Pacific/Chatham` - Pacific/Chatham
 * `Pacific/Chuuk` - Pacific/Chuuk
 * `Pacific/Easter` - Pacific/Easter
 * `Pacific/Efate` - Pacific/Efate
 * `Pacific/Enderbury` - Pacific/Enderbury
 * `Pacific/Fakaofo` - Pacific/Fakaofo
 * `Pacific/Fiji` - Pacific/Fiji
 * `Pacific/Funafuti` - Pacific/Funafuti
 * `Pacific/Galapagos` - Pacific/Galapagos
 * `Pacific/Gambier` - Pacific/Gambier
 * `Pacific/Guadalcanal` - Pacific/Guadalcanal
 * `Pacific/Guam` - Pacific/Guam
 * `Pacific/Honolulu` - Pacific/Honolulu
 * `Pacific/Johnston` - Pacific/Johnston
 * `Pacific/Kanton` - Pacific/Kanton
 * `Pacific/Kiritimati` - Pacific/Kiritimati
 * `Pacific/Kosrae` - Pacific/Kosrae
 * `Pacific/Kwajalein` - Pacific/Kwajalein
 * `Pacific/Majuro` - Pacific/Majuro
 * `Pacific/Marquesas` - Pacific/Marquesas
 * `Pacific/Midway` - Pacific/Midway
 * `Pacific/Nauru` - Pacific/Nauru
 * `Pacific/Niue` - Pacific/Niue
 * `Pacific/Norfolk` - Pacific/Norfolk
 * `Pacific/Noumea` - Pacific/Noumea
 * `Pacific/Pago_Pago` - Pacific/Pago_Pago
 * `Pacific/Palau` - Pacific/Palau
 * `Pacific/Pitcairn` - Pacific/Pitcairn
 * `Pacific/Pohnpei` - Pacific/Pohnpei
 * `Pacific/Ponape` - Pacific/Ponape
 * `Pacific/Port_Moresby` - Pacific/Port_Moresby
 * `Pacific/Rarotonga` - Pacific/Rarotonga
 * `Pacific/Saipan` - Pacific/Saipan
 * `Pacific/Samoa` - Pacific/Samoa
 * `Pacific/Tahiti` - Pacific/Tahiti
 * `Pacific/Tarawa` - Pacific/Tarawa
 * `Pacific/Tongatapu` - Pacific/Tongatapu
 * `Pacific/Truk` - Pacific/Truk
 * `Pacific/Wake` - Pacific/Wake
 * `Pacific/Wallis` - Pacific/Wallis
 * `Pacific/Yap` - Pacific/Yap
 * `Poland` - Poland
 * `Portugal` - Portugal
 * `ROC` - ROC
 * `ROK` - ROK
 * `Singapore` - Singapore
 * `Turkey` - Turkey
 * `UCT` - UCT
 * `US/Alaska` - US/Alaska
 * `US/Aleutian` - US/Aleutian
 * `US/Arizona` - US/Arizona
 * `US/Central` - US/Central
 * `US/East-Indiana` - US/East-Indiana
 * `US/Eastern` - US/Eastern
 * `US/Hawaii` - US/Hawaii
 * `US/Indiana-Starke` - US/Indiana-Starke
 * `US/Michigan` - US/Michigan
 * `US/Mountain` - US/Mountain
 * `US/Pacific` - US/Pacific
 * `US/Samoa` - US/Samoa
 * `UTC` - UTC
 * `Universal` - Universal
 * `W-SU` - W-SU
 * `WET` - WET
 * `Zulu` - Zulu
 */
export type TimezoneEnumApi = (typeof TimezoneEnumApi)[keyof typeof TimezoneEnumApi]

export const TimezoneEnumApi = {
    AfricaAbidjan: 'Africa/Abidjan',
    AfricaAccra: 'Africa/Accra',
    AfricaAddisAbaba: 'Africa/Addis_Ababa',
    AfricaAlgiers: 'Africa/Algiers',
    AfricaAsmara: 'Africa/Asmara',
    AfricaAsmera: 'Africa/Asmera',
    AfricaBamako: 'Africa/Bamako',
    AfricaBangui: 'Africa/Bangui',
    AfricaBanjul: 'Africa/Banjul',
    AfricaBissau: 'Africa/Bissau',
    AfricaBlantyre: 'Africa/Blantyre',
    AfricaBrazzaville: 'Africa/Brazzaville',
    AfricaBujumbura: 'Africa/Bujumbura',
    AfricaCairo: 'Africa/Cairo',
    AfricaCasablanca: 'Africa/Casablanca',
    AfricaCeuta: 'Africa/Ceuta',
    AfricaConakry: 'Africa/Conakry',
    AfricaDakar: 'Africa/Dakar',
    AfricaDarEsSalaam: 'Africa/Dar_es_Salaam',
    AfricaDjibouti: 'Africa/Djibouti',
    AfricaDouala: 'Africa/Douala',
    AfricaElAaiun: 'Africa/El_Aaiun',
    AfricaFreetown: 'Africa/Freetown',
    AfricaGaborone: 'Africa/Gaborone',
    AfricaHarare: 'Africa/Harare',
    AfricaJohannesburg: 'Africa/Johannesburg',
    AfricaJuba: 'Africa/Juba',
    AfricaKampala: 'Africa/Kampala',
    AfricaKhartoum: 'Africa/Khartoum',
    AfricaKigali: 'Africa/Kigali',
    AfricaKinshasa: 'Africa/Kinshasa',
    AfricaLagos: 'Africa/Lagos',
    AfricaLibreville: 'Africa/Libreville',
    AfricaLome: 'Africa/Lome',
    AfricaLuanda: 'Africa/Luanda',
    AfricaLubumbashi: 'Africa/Lubumbashi',
    AfricaLusaka: 'Africa/Lusaka',
    AfricaMalabo: 'Africa/Malabo',
    AfricaMaputo: 'Africa/Maputo',
    AfricaMaseru: 'Africa/Maseru',
    AfricaMbabane: 'Africa/Mbabane',
    AfricaMogadishu: 'Africa/Mogadishu',
    AfricaMonrovia: 'Africa/Monrovia',
    AfricaNairobi: 'Africa/Nairobi',
    AfricaNdjamena: 'Africa/Ndjamena',
    AfricaNiamey: 'Africa/Niamey',
    AfricaNouakchott: 'Africa/Nouakchott',
    AfricaOuagadougou: 'Africa/Ouagadougou',
    AfricaPortoNovo: 'Africa/Porto-Novo',
    AfricaSaoTome: 'Africa/Sao_Tome',
    AfricaTimbuktu: 'Africa/Timbuktu',
    AfricaTripoli: 'Africa/Tripoli',
    AfricaTunis: 'Africa/Tunis',
    AfricaWindhoek: 'Africa/Windhoek',
    AmericaAdak: 'America/Adak',
    AmericaAnchorage: 'America/Anchorage',
    AmericaAnguilla: 'America/Anguilla',
    AmericaAntigua: 'America/Antigua',
    AmericaAraguaina: 'America/Araguaina',
    AmericaArgentinaBuenosAires: 'America/Argentina/Buenos_Aires',
    AmericaArgentinaCatamarca: 'America/Argentina/Catamarca',
    AmericaArgentinaComodRivadavia: 'America/Argentina/ComodRivadavia',
    AmericaArgentinaCordoba: 'America/Argentina/Cordoba',
    AmericaArgentinaJujuy: 'America/Argentina/Jujuy',
    AmericaArgentinaLaRioja: 'America/Argentina/La_Rioja',
    AmericaArgentinaMendoza: 'America/Argentina/Mendoza',
    AmericaArgentinaRioGallegos: 'America/Argentina/Rio_Gallegos',
    AmericaArgentinaSalta: 'America/Argentina/Salta',
    AmericaArgentinaSanJuan: 'America/Argentina/San_Juan',
    AmericaArgentinaSanLuis: 'America/Argentina/San_Luis',
    AmericaArgentinaTucuman: 'America/Argentina/Tucuman',
    AmericaArgentinaUshuaia: 'America/Argentina/Ushuaia',
    AmericaAruba: 'America/Aruba',
    AmericaAsuncion: 'America/Asuncion',
    AmericaAtikokan: 'America/Atikokan',
    AmericaAtka: 'America/Atka',
    AmericaBahia: 'America/Bahia',
    AmericaBahiaBanderas: 'America/Bahia_Banderas',
    AmericaBarbados: 'America/Barbados',
    AmericaBelem: 'America/Belem',
    AmericaBelize: 'America/Belize',
    AmericaBlancSablon: 'America/Blanc-Sablon',
    AmericaBoaVista: 'America/Boa_Vista',
    AmericaBogota: 'America/Bogota',
    AmericaBoise: 'America/Boise',
    AmericaBuenosAires: 'America/Buenos_Aires',
    AmericaCambridgeBay: 'America/Cambridge_Bay',
    AmericaCampoGrande: 'America/Campo_Grande',
    AmericaCancun: 'America/Cancun',
    AmericaCaracas: 'America/Caracas',
    AmericaCatamarca: 'America/Catamarca',
    AmericaCayenne: 'America/Cayenne',
    AmericaCayman: 'America/Cayman',
    AmericaChicago: 'America/Chicago',
    AmericaChihuahua: 'America/Chihuahua',
    AmericaCiudadJuarez: 'America/Ciudad_Juarez',
    AmericaCoralHarbour: 'America/Coral_Harbour',
    AmericaCordoba: 'America/Cordoba',
    AmericaCostaRica: 'America/Costa_Rica',
    AmericaCreston: 'America/Creston',
    AmericaCuiaba: 'America/Cuiaba',
    AmericaCuracao: 'America/Curacao',
    AmericaDanmarkshavn: 'America/Danmarkshavn',
    AmericaDawson: 'America/Dawson',
    AmericaDawsonCreek: 'America/Dawson_Creek',
    AmericaDenver: 'America/Denver',
    AmericaDetroit: 'America/Detroit',
    AmericaDominica: 'America/Dominica',
    AmericaEdmonton: 'America/Edmonton',
    AmericaEirunepe: 'America/Eirunepe',
    AmericaElSalvador: 'America/El_Salvador',
    AmericaEnsenada: 'America/Ensenada',
    AmericaFortNelson: 'America/Fort_Nelson',
    AmericaFortWayne: 'America/Fort_Wayne',
    AmericaFortaleza: 'America/Fortaleza',
    AmericaGlaceBay: 'America/Glace_Bay',
    AmericaGodthab: 'America/Godthab',
    AmericaGooseBay: 'America/Goose_Bay',
    AmericaGrandTurk: 'America/Grand_Turk',
    AmericaGrenada: 'America/Grenada',
    AmericaGuadeloupe: 'America/Guadeloupe',
    AmericaGuatemala: 'America/Guatemala',
    AmericaGuayaquil: 'America/Guayaquil',
    AmericaGuyana: 'America/Guyana',
    AmericaHalifax: 'America/Halifax',
    AmericaHavana: 'America/Havana',
    AmericaHermosillo: 'America/Hermosillo',
    AmericaIndianaIndianapolis: 'America/Indiana/Indianapolis',
    AmericaIndianaKnox: 'America/Indiana/Knox',
    AmericaIndianaMarengo: 'America/Indiana/Marengo',
    AmericaIndianaPetersburg: 'America/Indiana/Petersburg',
    AmericaIndianaTellCity: 'America/Indiana/Tell_City',
    AmericaIndianaVevay: 'America/Indiana/Vevay',
    AmericaIndianaVincennes: 'America/Indiana/Vincennes',
    AmericaIndianaWinamac: 'America/Indiana/Winamac',
    AmericaIndianapolis: 'America/Indianapolis',
    AmericaInuvik: 'America/Inuvik',
    AmericaIqaluit: 'America/Iqaluit',
    AmericaJamaica: 'America/Jamaica',
    AmericaJujuy: 'America/Jujuy',
    AmericaJuneau: 'America/Juneau',
    AmericaKentuckyLouisville: 'America/Kentucky/Louisville',
    AmericaKentuckyMonticello: 'America/Kentucky/Monticello',
    AmericaKnoxIN: 'America/Knox_IN',
    AmericaKralendijk: 'America/Kralendijk',
    AmericaLaPaz: 'America/La_Paz',
    AmericaLima: 'America/Lima',
    AmericaLosAngeles: 'America/Los_Angeles',
    AmericaLouisville: 'America/Louisville',
    AmericaLowerPrinces: 'America/Lower_Princes',
    AmericaMaceio: 'America/Maceio',
    AmericaManagua: 'America/Managua',
    AmericaManaus: 'America/Manaus',
    AmericaMarigot: 'America/Marigot',
    AmericaMartinique: 'America/Martinique',
    AmericaMatamoros: 'America/Matamoros',
    AmericaMazatlan: 'America/Mazatlan',
    AmericaMendoza: 'America/Mendoza',
    AmericaMenominee: 'America/Menominee',
    AmericaMerida: 'America/Merida',
    AmericaMetlakatla: 'America/Metlakatla',
    AmericaMexicoCity: 'America/Mexico_City',
    AmericaMiquelon: 'America/Miquelon',
    AmericaMoncton: 'America/Moncton',
    AmericaMonterrey: 'America/Monterrey',
    AmericaMontevideo: 'America/Montevideo',
    AmericaMontreal: 'America/Montreal',
    AmericaMontserrat: 'America/Montserrat',
    AmericaNassau: 'America/Nassau',
    AmericaNewYork: 'America/New_York',
    AmericaNipigon: 'America/Nipigon',
    AmericaNome: 'America/Nome',
    AmericaNoronha: 'America/Noronha',
    AmericaNorthDakotaBeulah: 'America/North_Dakota/Beulah',
    AmericaNorthDakotaCenter: 'America/North_Dakota/Center',
    AmericaNorthDakotaNewSalem: 'America/North_Dakota/New_Salem',
    AmericaNuuk: 'America/Nuuk',
    AmericaOjinaga: 'America/Ojinaga',
    AmericaPanama: 'America/Panama',
    AmericaPangnirtung: 'America/Pangnirtung',
    AmericaParamaribo: 'America/Paramaribo',
    AmericaPhoenix: 'America/Phoenix',
    AmericaPortAuPrince: 'America/Port-au-Prince',
    AmericaPortOfSpain: 'America/Port_of_Spain',
    AmericaPortoAcre: 'America/Porto_Acre',
    AmericaPortoVelho: 'America/Porto_Velho',
    AmericaPuertoRico: 'America/Puerto_Rico',
    AmericaPuntaArenas: 'America/Punta_Arenas',
    AmericaRainyRiver: 'America/Rainy_River',
    AmericaRankinInlet: 'America/Rankin_Inlet',
    AmericaRecife: 'America/Recife',
    AmericaRegina: 'America/Regina',
    AmericaResolute: 'America/Resolute',
    AmericaRioBranco: 'America/Rio_Branco',
    AmericaRosario: 'America/Rosario',
    AmericaSantaIsabel: 'America/Santa_Isabel',
    AmericaSantarem: 'America/Santarem',
    AmericaSantiago: 'America/Santiago',
    AmericaSantoDomingo: 'America/Santo_Domingo',
    AmericaSaoPaulo: 'America/Sao_Paulo',
    AmericaScoresbysund: 'America/Scoresbysund',
    AmericaShiprock: 'America/Shiprock',
    AmericaSitka: 'America/Sitka',
    AmericaStBarthelemy: 'America/St_Barthelemy',
    AmericaStJohns: 'America/St_Johns',
    AmericaStKitts: 'America/St_Kitts',
    AmericaStLucia: 'America/St_Lucia',
    AmericaStThomas: 'America/St_Thomas',
    AmericaStVincent: 'America/St_Vincent',
    AmericaSwiftCurrent: 'America/Swift_Current',
    AmericaTegucigalpa: 'America/Tegucigalpa',
    AmericaThule: 'America/Thule',
    AmericaThunderBay: 'America/Thunder_Bay',
    AmericaTijuana: 'America/Tijuana',
    AmericaToronto: 'America/Toronto',
    AmericaTortola: 'America/Tortola',
    AmericaVancouver: 'America/Vancouver',
    AmericaVirgin: 'America/Virgin',
    AmericaWhitehorse: 'America/Whitehorse',
    AmericaWinnipeg: 'America/Winnipeg',
    AmericaYakutat: 'America/Yakutat',
    AmericaYellowknife: 'America/Yellowknife',
    AntarcticaCasey: 'Antarctica/Casey',
    AntarcticaDavis: 'Antarctica/Davis',
    AntarcticaDumontDUrville: 'Antarctica/DumontDUrville',
    AntarcticaMacquarie: 'Antarctica/Macquarie',
    AntarcticaMawson: 'Antarctica/Mawson',
    AntarcticaMcMurdo: 'Antarctica/McMurdo',
    AntarcticaPalmer: 'Antarctica/Palmer',
    AntarcticaRothera: 'Antarctica/Rothera',
    AntarcticaSouthPole: 'Antarctica/South_Pole',
    AntarcticaSyowa: 'Antarctica/Syowa',
    AntarcticaTroll: 'Antarctica/Troll',
    AntarcticaVostok: 'Antarctica/Vostok',
    ArcticLongyearbyen: 'Arctic/Longyearbyen',
    AsiaAden: 'Asia/Aden',
    AsiaAlmaty: 'Asia/Almaty',
    AsiaAmman: 'Asia/Amman',
    AsiaAnadyr: 'Asia/Anadyr',
    AsiaAqtau: 'Asia/Aqtau',
    AsiaAqtobe: 'Asia/Aqtobe',
    AsiaAshgabat: 'Asia/Ashgabat',
    AsiaAshkhabad: 'Asia/Ashkhabad',
    AsiaAtyrau: 'Asia/Atyrau',
    AsiaBaghdad: 'Asia/Baghdad',
    AsiaBahrain: 'Asia/Bahrain',
    AsiaBaku: 'Asia/Baku',
    AsiaBangkok: 'Asia/Bangkok',
    AsiaBarnaul: 'Asia/Barnaul',
    AsiaBeirut: 'Asia/Beirut',
    AsiaBishkek: 'Asia/Bishkek',
    AsiaBrunei: 'Asia/Brunei',
    AsiaCalcutta: 'Asia/Calcutta',
    AsiaChita: 'Asia/Chita',
    AsiaChoibalsan: 'Asia/Choibalsan',
    AsiaChongqing: 'Asia/Chongqing',
    AsiaChungking: 'Asia/Chungking',
    AsiaColombo: 'Asia/Colombo',
    AsiaDacca: 'Asia/Dacca',
    AsiaDamascus: 'Asia/Damascus',
    AsiaDhaka: 'Asia/Dhaka',
    AsiaDili: 'Asia/Dili',
    AsiaDubai: 'Asia/Dubai',
    AsiaDushanbe: 'Asia/Dushanbe',
    AsiaFamagusta: 'Asia/Famagusta',
    AsiaGaza: 'Asia/Gaza',
    AsiaHarbin: 'Asia/Harbin',
    AsiaHebron: 'Asia/Hebron',
    AsiaHoChiMinh: 'Asia/Ho_Chi_Minh',
    AsiaHongKong: 'Asia/Hong_Kong',
    AsiaHovd: 'Asia/Hovd',
    AsiaIrkutsk: 'Asia/Irkutsk',
    AsiaIstanbul: 'Asia/Istanbul',
    AsiaJakarta: 'Asia/Jakarta',
    AsiaJayapura: 'Asia/Jayapura',
    AsiaJerusalem: 'Asia/Jerusalem',
    AsiaKabul: 'Asia/Kabul',
    AsiaKamchatka: 'Asia/Kamchatka',
    AsiaKarachi: 'Asia/Karachi',
    AsiaKashgar: 'Asia/Kashgar',
    AsiaKathmandu: 'Asia/Kathmandu',
    AsiaKatmandu: 'Asia/Katmandu',
    AsiaKhandyga: 'Asia/Khandyga',
    AsiaKolkata: 'Asia/Kolkata',
    AsiaKrasnoyarsk: 'Asia/Krasnoyarsk',
    AsiaKualaLumpur: 'Asia/Kuala_Lumpur',
    AsiaKuching: 'Asia/Kuching',
    AsiaKuwait: 'Asia/Kuwait',
    AsiaMacao: 'Asia/Macao',
    AsiaMacau: 'Asia/Macau',
    AsiaMagadan: 'Asia/Magadan',
    AsiaMakassar: 'Asia/Makassar',
    AsiaManila: 'Asia/Manila',
    AsiaMuscat: 'Asia/Muscat',
    AsiaNicosia: 'Asia/Nicosia',
    AsiaNovokuznetsk: 'Asia/Novokuznetsk',
    AsiaNovosibirsk: 'Asia/Novosibirsk',
    AsiaOmsk: 'Asia/Omsk',
    AsiaOral: 'Asia/Oral',
    AsiaPhnomPenh: 'Asia/Phnom_Penh',
    AsiaPontianak: 'Asia/Pontianak',
    AsiaPyongyang: 'Asia/Pyongyang',
    AsiaQatar: 'Asia/Qatar',
    AsiaQostanay: 'Asia/Qostanay',
    AsiaQyzylorda: 'Asia/Qyzylorda',
    AsiaRangoon: 'Asia/Rangoon',
    AsiaRiyadh: 'Asia/Riyadh',
    AsiaSaigon: 'Asia/Saigon',
    AsiaSakhalin: 'Asia/Sakhalin',
    AsiaSamarkand: 'Asia/Samarkand',
    AsiaSeoul: 'Asia/Seoul',
    AsiaShanghai: 'Asia/Shanghai',
    AsiaSingapore: 'Asia/Singapore',
    AsiaSrednekolymsk: 'Asia/Srednekolymsk',
    AsiaTaipei: 'Asia/Taipei',
    AsiaTashkent: 'Asia/Tashkent',
    AsiaTbilisi: 'Asia/Tbilisi',
    AsiaTehran: 'Asia/Tehran',
    AsiaTelAviv: 'Asia/Tel_Aviv',
    AsiaThimbu: 'Asia/Thimbu',
    AsiaThimphu: 'Asia/Thimphu',
    AsiaTokyo: 'Asia/Tokyo',
    AsiaTomsk: 'Asia/Tomsk',
    AsiaUjungPandang: 'Asia/Ujung_Pandang',
    AsiaUlaanbaatar: 'Asia/Ulaanbaatar',
    AsiaUlanBator: 'Asia/Ulan_Bator',
    AsiaUrumqi: 'Asia/Urumqi',
    AsiaUstNera: 'Asia/Ust-Nera',
    AsiaVientiane: 'Asia/Vientiane',
    AsiaVladivostok: 'Asia/Vladivostok',
    AsiaYakutsk: 'Asia/Yakutsk',
    AsiaYangon: 'Asia/Yangon',
    AsiaYekaterinburg: 'Asia/Yekaterinburg',
    AsiaYerevan: 'Asia/Yerevan',
    AtlanticAzores: 'Atlantic/Azores',
    AtlanticBermuda: 'Atlantic/Bermuda',
    AtlanticCanary: 'Atlantic/Canary',
    AtlanticCapeVerde: 'Atlantic/Cape_Verde',
    AtlanticFaeroe: 'Atlantic/Faeroe',
    AtlanticFaroe: 'Atlantic/Faroe',
    AtlanticJanMayen: 'Atlantic/Jan_Mayen',
    AtlanticMadeira: 'Atlantic/Madeira',
    AtlanticReykjavik: 'Atlantic/Reykjavik',
    AtlanticSouthGeorgia: 'Atlantic/South_Georgia',
    AtlanticStHelena: 'Atlantic/St_Helena',
    AtlanticStanley: 'Atlantic/Stanley',
    AustraliaACT: 'Australia/ACT',
    AustraliaAdelaide: 'Australia/Adelaide',
    AustraliaBrisbane: 'Australia/Brisbane',
    AustraliaBrokenHill: 'Australia/Broken_Hill',
    AustraliaCanberra: 'Australia/Canberra',
    AustraliaCurrie: 'Australia/Currie',
    AustraliaDarwin: 'Australia/Darwin',
    AustraliaEucla: 'Australia/Eucla',
    AustraliaHobart: 'Australia/Hobart',
    AustraliaLHI: 'Australia/LHI',
    AustraliaLindeman: 'Australia/Lindeman',
    AustraliaLordHowe: 'Australia/Lord_Howe',
    AustraliaMelbourne: 'Australia/Melbourne',
    AustraliaNSW: 'Australia/NSW',
    AustraliaNorth: 'Australia/North',
    AustraliaPerth: 'Australia/Perth',
    AustraliaQueensland: 'Australia/Queensland',
    AustraliaSouth: 'Australia/South',
    AustraliaSydney: 'Australia/Sydney',
    AustraliaTasmania: 'Australia/Tasmania',
    AustraliaVictoria: 'Australia/Victoria',
    AustraliaWest: 'Australia/West',
    AustraliaYancowinna: 'Australia/Yancowinna',
    BrazilAcre: 'Brazil/Acre',
    BrazilDeNoronha: 'Brazil/DeNoronha',
    BrazilEast: 'Brazil/East',
    BrazilWest: 'Brazil/West',
    Cet: 'CET',
    Cst6cdt: 'CST6CDT',
    CanadaAtlantic: 'Canada/Atlantic',
    CanadaCentral: 'Canada/Central',
    CanadaEastern: 'Canada/Eastern',
    CanadaMountain: 'Canada/Mountain',
    CanadaNewfoundland: 'Canada/Newfoundland',
    CanadaPacific: 'Canada/Pacific',
    CanadaSaskatchewan: 'Canada/Saskatchewan',
    CanadaYukon: 'Canada/Yukon',
    ChileContinental: 'Chile/Continental',
    ChileEasterIsland: 'Chile/EasterIsland',
    Cuba: 'Cuba',
    Eet: 'EET',
    Est: 'EST',
    Est5edt: 'EST5EDT',
    Egypt: 'Egypt',
    Eire: 'Eire',
    EtcGMT: 'Etc/GMT',
    EtcGMT0: 'Etc/GMT+0',
    EtcGMT1: 'Etc/GMT+1',
    EtcGMT10: 'Etc/GMT+10',
    EtcGMT11: 'Etc/GMT+11',
    EtcGMT12: 'Etc/GMT+12',
    EtcGMT2: 'Etc/GMT+2',
    EtcGMT3: 'Etc/GMT+3',
    EtcGMT4: 'Etc/GMT+4',
    EtcGMT5: 'Etc/GMT+5',
    EtcGMT6: 'Etc/GMT+6',
    EtcGMT7: 'Etc/GMT+7',
    EtcGMT8: 'Etc/GMT+8',
    EtcGMT9: 'Etc/GMT+9',
    EtcGMT0: 'Etc/GMT-0',
    EtcGMT1: 'Etc/GMT-1',
    EtcGMT10: 'Etc/GMT-10',
    EtcGMT11: 'Etc/GMT-11',
    EtcGMT12: 'Etc/GMT-12',
    EtcGMT13: 'Etc/GMT-13',
    EtcGMT14: 'Etc/GMT-14',
    EtcGMT2: 'Etc/GMT-2',
    EtcGMT3: 'Etc/GMT-3',
    EtcGMT4: 'Etc/GMT-4',
    EtcGMT5: 'Etc/GMT-5',
    EtcGMT6: 'Etc/GMT-6',
    EtcGMT7: 'Etc/GMT-7',
    EtcGMT8: 'Etc/GMT-8',
    EtcGMT9: 'Etc/GMT-9',
    EtcGMT0: 'Etc/GMT0',
    EtcGreenwich: 'Etc/Greenwich',
    EtcUCT: 'Etc/UCT',
    EtcUTC: 'Etc/UTC',
    EtcUniversal: 'Etc/Universal',
    EtcZulu: 'Etc/Zulu',
    EuropeAmsterdam: 'Europe/Amsterdam',
    EuropeAndorra: 'Europe/Andorra',
    EuropeAstrakhan: 'Europe/Astrakhan',
    EuropeAthens: 'Europe/Athens',
    EuropeBelfast: 'Europe/Belfast',
    EuropeBelgrade: 'Europe/Belgrade',
    EuropeBerlin: 'Europe/Berlin',
    EuropeBratislava: 'Europe/Bratislava',
    EuropeBrussels: 'Europe/Brussels',
    EuropeBucharest: 'Europe/Bucharest',
    EuropeBudapest: 'Europe/Budapest',
    EuropeBusingen: 'Europe/Busingen',
    EuropeChisinau: 'Europe/Chisinau',
    EuropeCopenhagen: 'Europe/Copenhagen',
    EuropeDublin: 'Europe/Dublin',
    EuropeGibraltar: 'Europe/Gibraltar',
    EuropeGuernsey: 'Europe/Guernsey',
    EuropeHelsinki: 'Europe/Helsinki',
    EuropeIsleOfMan: 'Europe/Isle_of_Man',
    EuropeIstanbul: 'Europe/Istanbul',
    EuropeJersey: 'Europe/Jersey',
    EuropeKaliningrad: 'Europe/Kaliningrad',
    EuropeKiev: 'Europe/Kiev',
    EuropeKirov: 'Europe/Kirov',
    EuropeKyiv: 'Europe/Kyiv',
    EuropeLisbon: 'Europe/Lisbon',
    EuropeLjubljana: 'Europe/Ljubljana',
    EuropeLondon: 'Europe/London',
    EuropeLuxembourg: 'Europe/Luxembourg',
    EuropeMadrid: 'Europe/Madrid',
    EuropeMalta: 'Europe/Malta',
    EuropeMariehamn: 'Europe/Mariehamn',
    EuropeMinsk: 'Europe/Minsk',
    EuropeMonaco: 'Europe/Monaco',
    EuropeMoscow: 'Europe/Moscow',
    EuropeNicosia: 'Europe/Nicosia',
    EuropeOslo: 'Europe/Oslo',
    EuropeParis: 'Europe/Paris',
    EuropePodgorica: 'Europe/Podgorica',
    EuropePrague: 'Europe/Prague',
    EuropeRiga: 'Europe/Riga',
    EuropeRome: 'Europe/Rome',
    EuropeSamara: 'Europe/Samara',
    EuropeSanMarino: 'Europe/San_Marino',
    EuropeSarajevo: 'Europe/Sarajevo',
    EuropeSaratov: 'Europe/Saratov',
    EuropeSimferopol: 'Europe/Simferopol',
    EuropeSkopje: 'Europe/Skopje',
    EuropeSofia: 'Europe/Sofia',
    EuropeStockholm: 'Europe/Stockholm',
    EuropeTallinn: 'Europe/Tallinn',
    EuropeTirane: 'Europe/Tirane',
    EuropeTiraspol: 'Europe/Tiraspol',
    EuropeUlyanovsk: 'Europe/Ulyanovsk',
    EuropeUzhgorod: 'Europe/Uzhgorod',
    EuropeVaduz: 'Europe/Vaduz',
    EuropeVatican: 'Europe/Vatican',
    EuropeVienna: 'Europe/Vienna',
    EuropeVilnius: 'Europe/Vilnius',
    EuropeVolgograd: 'Europe/Volgograd',
    EuropeWarsaw: 'Europe/Warsaw',
    EuropeZagreb: 'Europe/Zagreb',
    EuropeZaporozhye: 'Europe/Zaporozhye',
    EuropeZurich: 'Europe/Zurich',
    Gb: 'GB',
    GBEire: 'GB-Eire',
    Gmt: 'GMT',
    Gmt0: 'GMT+0',
    Gmt0: 'GMT-0',
    Gmt0: 'GMT0',
    Greenwich: 'Greenwich',
    Hst: 'HST',
    Hongkong: 'Hongkong',
    Iceland: 'Iceland',
    IndianAntananarivo: 'Indian/Antananarivo',
    IndianChagos: 'Indian/Chagos',
    IndianChristmas: 'Indian/Christmas',
    IndianCocos: 'Indian/Cocos',
    IndianComoro: 'Indian/Comoro',
    IndianKerguelen: 'Indian/Kerguelen',
    IndianMahe: 'Indian/Mahe',
    IndianMaldives: 'Indian/Maldives',
    IndianMauritius: 'Indian/Mauritius',
    IndianMayotte: 'Indian/Mayotte',
    IndianReunion: 'Indian/Reunion',
    Iran: 'Iran',
    Israel: 'Israel',
    Jamaica: 'Jamaica',
    Japan: 'Japan',
    Kwajalein: 'Kwajalein',
    Libya: 'Libya',
    Met: 'MET',
    Mst: 'MST',
    Mst7mdt: 'MST7MDT',
    MexicoBajaNorte: 'Mexico/BajaNorte',
    MexicoBajaSur: 'Mexico/BajaSur',
    MexicoGeneral: 'Mexico/General',
    Nz: 'NZ',
    NzChat: 'NZ-CHAT',
    Navajo: 'Navajo',
    Prc: 'PRC',
    Pst8pdt: 'PST8PDT',
    PacificApia: 'Pacific/Apia',
    PacificAuckland: 'Pacific/Auckland',
    PacificBougainville: 'Pacific/Bougainville',
    PacificChatham: 'Pacific/Chatham',
    PacificChuuk: 'Pacific/Chuuk',
    PacificEaster: 'Pacific/Easter',
    PacificEfate: 'Pacific/Efate',
    PacificEnderbury: 'Pacific/Enderbury',
    PacificFakaofo: 'Pacific/Fakaofo',
    PacificFiji: 'Pacific/Fiji',
    PacificFunafuti: 'Pacific/Funafuti',
    PacificGalapagos: 'Pacific/Galapagos',
    PacificGambier: 'Pacific/Gambier',
    PacificGuadalcanal: 'Pacific/Guadalcanal',
    PacificGuam: 'Pacific/Guam',
    PacificHonolulu: 'Pacific/Honolulu',
    PacificJohnston: 'Pacific/Johnston',
    PacificKanton: 'Pacific/Kanton',
    PacificKiritimati: 'Pacific/Kiritimati',
    PacificKosrae: 'Pacific/Kosrae',
    PacificKwajalein: 'Pacific/Kwajalein',
    PacificMajuro: 'Pacific/Majuro',
    PacificMarquesas: 'Pacific/Marquesas',
    PacificMidway: 'Pacific/Midway',
    PacificNauru: 'Pacific/Nauru',
    PacificNiue: 'Pacific/Niue',
    PacificNorfolk: 'Pacific/Norfolk',
    PacificNoumea: 'Pacific/Noumea',
    PacificPagoPago: 'Pacific/Pago_Pago',
    PacificPalau: 'Pacific/Palau',
    PacificPitcairn: 'Pacific/Pitcairn',
    PacificPohnpei: 'Pacific/Pohnpei',
    PacificPonape: 'Pacific/Ponape',
    PacificPortMoresby: 'Pacific/Port_Moresby',
    PacificRarotonga: 'Pacific/Rarotonga',
    PacificSaipan: 'Pacific/Saipan',
    PacificSamoa: 'Pacific/Samoa',
    PacificTahiti: 'Pacific/Tahiti',
    PacificTarawa: 'Pacific/Tarawa',
    PacificTongatapu: 'Pacific/Tongatapu',
    PacificTruk: 'Pacific/Truk',
    PacificWake: 'Pacific/Wake',
    PacificWallis: 'Pacific/Wallis',
    PacificYap: 'Pacific/Yap',
    Poland: 'Poland',
    Portugal: 'Portugal',
    Roc: 'ROC',
    Rok: 'ROK',
    Singapore: 'Singapore',
    Turkey: 'Turkey',
    Uct: 'UCT',
    USAlaska: 'US/Alaska',
    USAleutian: 'US/Aleutian',
    USArizona: 'US/Arizona',
    USCentral: 'US/Central',
    USEastIndiana: 'US/East-Indiana',
    USEastern: 'US/Eastern',
    USHawaii: 'US/Hawaii',
    USIndianaStarke: 'US/Indiana-Starke',
    USMichigan: 'US/Michigan',
    USMountain: 'US/Mountain',
    USPacific: 'US/Pacific',
    USSamoa: 'US/Samoa',
    Utc: 'UTC',
    Universal: 'Universal',
    WSu: 'W-SU',
    Wet: 'WET',
    Zulu: 'Zulu',
} as const

/**
 * Serializer for a BatchExport model.
 */
export interface BatchExportApi {
    readonly id: string
    /** The team this belongs to. */
    readonly team_id: number
    /** A human-readable name for this BatchExport. */
    name: string
    /** Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions */
    model?: ModelEnumApi | BlankEnumApi | NullEnumApi | null
    destination: BatchExportDestinationApi
    interval: IntervalEnumApi
    /** Whether this BatchExport is paused or not. */
    paused?: boolean
    /** The timestamp at which this BatchExport was created. */
    readonly created_at: string
    /** The timestamp at which this BatchExport was last updated. */
    readonly last_updated_at: string
    /**
     * The timestamp at which this BatchExport was last paused.
     * @nullable
     */
    last_paused_at?: string | null
    /**
     * Time before which any Batch Export runs won't be triggered.
     * @nullable
     */
    start_at?: string | null
    /**
     * Time after which any Batch Export runs won't be triggered.
     * @nullable
     */
    end_at?: string | null
    readonly latest_runs: readonly BatchExportRunApi[]
    hogql_query?: string
    /** A schema of custom fields to select when exporting data. */
    readonly schema: unknown | null
    filters?: unknown | null
    timezone?: TimezoneEnumApi | NullEnumApi | null
    /**
     * @minimum 0
     * @maximum 6
     * @nullable
     */
    offset_day?: number | null
    /**
     * @minimum 0
     * @maximum 23
     * @nullable
     */
    offset_hour?: number | null
}

export interface PaginatedBatchExportListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchExportApi[]
}

/**
 * * `Cancelled` - Cancelled
 * `Completed` - Completed
 * `ContinuedAsNew` - Continued As New
 * `Failed` - Failed
 * `FailedRetryable` - Failed Retryable
 * `Terminated` - Terminated
 * `TimedOut` - Timedout
 * `Running` - Running
 * `Starting` - Starting
 */
export type BatchExportBackfillStatusEnumApi =
    (typeof BatchExportBackfillStatusEnumApi)[keyof typeof BatchExportBackfillStatusEnumApi]

export const BatchExportBackfillStatusEnumApi = {
    Cancelled: 'Cancelled',
    Completed: 'Completed',
    ContinuedAsNew: 'ContinuedAsNew',
    Failed: 'Failed',
    FailedRetryable: 'FailedRetryable',
    Terminated: 'Terminated',
    TimedOut: 'TimedOut',
    Running: 'Running',
    Starting: 'Starting',
} as const

export interface BatchExportBackfillApi {
    readonly id: string
    readonly progress: string
    /**
     * The start of the data interval.
     * @nullable
     */
    start_at?: string | null
    /**
     * The end of the data interval.
     * @nullable
     */
    end_at?: string | null
    /** The status of this backfill.

* `Cancelled` - Cancelled
* `Completed` - Completed
* `ContinuedAsNew` - Continued As New
* `Failed` - Failed
* `FailedRetryable` - Failed Retryable
* `Terminated` - Terminated
* `TimedOut` - Timedout
* `Running` - Running
* `Starting` - Starting */
    status: BatchExportBackfillStatusEnumApi
    /** The timestamp at which this BatchExportBackfill was created. */
    readonly created_at: string
    /**
     * The timestamp at which this BatchExportBackfill finished, successfully or not.
     * @nullable
     */
    finished_at?: string | null
    /** The timestamp at which this BatchExportBackfill was last updated. */
    readonly last_updated_at: string
    /** The team this belongs to. */
    team: number
    /** The BatchExport this backfill belongs to. */
    batch_export: string
}

export interface PaginatedBatchExportBackfillListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchExportBackfillApi[]
}

export interface PaginatedBatchExportRunListApi {
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: BatchExportRunApi[]
}

/**
 * Serializer for a BatchExport model.
 */
export interface PatchedBatchExportApi {
    readonly id?: string
    /** The team this belongs to. */
    readonly team_id?: number
    /** A human-readable name for this BatchExport. */
    name?: string
    /** Which model this BatchExport is exporting.

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions */
    model?: ModelEnumApi | BlankEnumApi | NullEnumApi | null
    destination?: BatchExportDestinationApi
    interval?: IntervalEnumApi
    /** Whether this BatchExport is paused or not. */
    paused?: boolean
    /** The timestamp at which this BatchExport was created. */
    readonly created_at?: string
    /** The timestamp at which this BatchExport was last updated. */
    readonly last_updated_at?: string
    /**
     * The timestamp at which this BatchExport was last paused.
     * @nullable
     */
    last_paused_at?: string | null
    /**
     * Time before which any Batch Export runs won't be triggered.
     * @nullable
     */
    start_at?: string | null
    /**
     * Time after which any Batch Export runs won't be triggered.
     * @nullable
     */
    end_at?: string | null
    readonly latest_runs?: readonly BatchExportRunApi[]
    hogql_query?: string
    /** A schema of custom fields to select when exporting data. */
    readonly schema?: unknown | null
    filters?: unknown | null
    timezone?: TimezoneEnumApi | NullEnumApi | null
    /**
     * @minimum 0
     * @maximum 6
     * @nullable
     */
    offset_day?: number | null
    /**
     * @minimum 0
     * @maximum 23
     * @nullable
     */
    offset_hour?: number | null
}

export type BatchExportsListParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BatchExportsBackfillsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}

export type BatchExportsRunsListParams = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}

export type BatchExportsList2Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BatchExportsList3Params = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type BatchExportsBackfillsList2Params = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}

export type BatchExportsRunsList2Params = {
    /**
     * The pagination cursor value.
     */
    cursor?: string
    /**
     * Which field to use when ordering the results.
     */
    ordering?: string
}
