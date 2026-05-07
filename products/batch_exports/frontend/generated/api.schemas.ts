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
 * `FileDownload` - File Download
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
    FileDownload: 'FileDownload',
} as const

/**
 * Typed configuration for a Databricks batch-export destination.

Credentials live in the linked Integration, not in this config. Mirrors
`DatabricksBatchExportInputs` in `products/batch_exports/backend/service.py`.
 */
export interface DatabricksDestinationConfigApi {
    /** Databricks SQL warehouse HTTP path. */
    http_path: string
    /** Unity Catalog name. */
    catalog: string
    /** Schema (database) name inside the catalog. */
    schema: string
    /** Destination table name. */
    table_name: string
    /** Whether to use the Databricks VARIANT type for JSON-like columns. */
    use_variant_type?: boolean
    /** Whether to let Databricks evolve the destination table schema automatically. */
    use_automatic_schema_evolution?: boolean
}

/**
 * * `brotli` - brotli
 * `gzip` - gzip
 * `lz4` - lz4
 * `snappy` - snappy
 * `zstd` - zstd
 */
export type CompressionEnumApi = (typeof CompressionEnumApi)[keyof typeof CompressionEnumApi]

export const CompressionEnumApi = {
    Brotli: 'brotli',
    Gzip: 'gzip',
    Lz4: 'lz4',
    Snappy: 'snappy',
    Zstd: 'zstd',
} as const

/**
 * * `JSONLines` - JSONLines
 * `Parquet` - Parquet
 */
export type FileFormatEnumApi = (typeof FileFormatEnumApi)[keyof typeof FileFormatEnumApi]

export const FileFormatEnumApi = {
    JSONLines: 'JSONLines',
    Parquet: 'Parquet',
} as const

/**
 * Typed configuration for an Azure Blob Storage batch-export destination.

Credentials live in the linked Integration, not in this config. Mirrors
`AzureBlobBatchExportInputs` in `products/batch_exports/backend/service.py`.
 */
export interface AzureBlobDestinationConfigApi {
    /** Azure Blob Storage container name. */
    container_name: string
    /** Object key prefix applied to every exported file. */
    prefix?: string
    /** Optional compression codec applied to exported files. Valid codecs depend on file_format.

* `brotli` - brotli
* `gzip` - gzip
* `lz4` - lz4
* `snappy` - snappy
* `zstd` - zstd */
    compression?: CompressionEnumApi | NullEnumApi | null
    /** File format used for exported objects.

* `JSONLines` - JSONLines
* `Parquet` - Parquet */
    file_format?: FileFormatEnumApi
    /**
     * If set, rolls to a new file once the current file exceeds this size in MB.
     * @nullable
     */
    max_file_size_mb?: number | null
}

export type BatchExportDestinationConfigApi = DatabricksDestinationConfigApi | AzureBlobDestinationConfigApi

/**
 * Serializer for an BatchExportDestination model.

The `config` field is polymorphic and typed only for destinations that keep
credentials in the linked Integration (currently Databricks and AzureBlob).
Other destination types accept the same JSON shape but without a typed
OpenAPI schema. Secret fields are stripped from `config` on read.
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
* `NoOp` - Noop
* `FileDownload` - File Download */
    type: BatchExportDestinationTypeEnumApi
    /** Destination-specific configuration. Fields depend on `type`. Credentials for integration-backed destinations (Databricks, AzureBlob) are NOT stored here — they live in the linked Integration. Secret fields are stripped from responses. */
    config: BatchExportDestinationConfigApi
    /**
     * The integration for this destination.
     * @nullable
     */
    integration?: number | null
    /**
     * ID of a team-scoped Integration providing credentials. Required for Databricks and AzureBlob destinations; optional for BigQuery; unused for other types.
     * @nullable
     */
    integration_id?: number | null
}

/**
 * * `hour` - hour
 * `day` - day
 * `week` - week
 * `every 5 minutes` - every 5 minutes
 * `every 15 minutes` - every 15 minutes
 */
export type IntervalEnumApi = (typeof IntervalEnumApi)[keyof typeof IntervalEnumApi]

export const IntervalEnumApi = {
    Hour: 'hour',
    Day: 'day',
    Week: 'week',
    Every5Minutes: 'every 5 minutes',
    Every15Minutes: 'every 15 minutes',
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
     * The number of records that failed downstream processing (e.g. hog function execution errors).
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    records_failed?: number | null
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
     * @minimum -2147483648
     * @maximum 2147483647
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
    /** Destination configuration (type, config, and optional integration). */
    destination: BatchExportDestinationApi
    /** How often the batch export should run.

* `hour` - hour
* `day` - day
* `week` - week
* `every 5 minutes` - every 5 minutes
* `every 15 minutes` - every 15 minutes */
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
    /** The 10 most recent runs of this batch export, ordered newest first. */
    readonly latest_runs: readonly BatchExportRunApi[]
    /** Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases. */
    hogql_query?: string
    /** A schema of custom fields to select when exporting data. */
    readonly schema: unknown | null
    filters?: unknown | null
    /** IANA timezone name controlling daily and weekly interval boundaries. Defaults to UTC.

* `Africa/Abidjan` - Africa/Abidjan
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
* `Zulu` - Zulu */
    timezone?: string | NullEnumApi | null
    /**
     * Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday). Only valid when interval is 'week'.
     * @minimum 0
     * @maximum 6
     * @nullable
     */
    offset_day?: number | null
    /**
     * Hour-of-day offset (0-23) for daily and weekly intervals. Only valid when interval is 'day' or 'week'.
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

export type DatabricksDestinationRequestApiType =
    (typeof DatabricksDestinationRequestApiType)[keyof typeof DatabricksDestinationRequestApiType]

export const DatabricksDestinationRequestApiType = {
    Databricks: 'Databricks',
} as const

/**
 * Request shape for creating or updating a Databricks batch-export destination.
 */
export interface DatabricksDestinationRequestApi {
    type: DatabricksDestinationRequestApiType
    /** ID of a databricks-kind Integration. Use the integrations-list MCP tool to find one. */
    integration_id: number
    config: DatabricksDestinationConfigApi
}

export type AzureBlobDestinationRequestApiType =
    (typeof AzureBlobDestinationRequestApiType)[keyof typeof AzureBlobDestinationRequestApiType]

export const AzureBlobDestinationRequestApiType = {
    AzureBlob: 'AzureBlob',
} as const

/**
 * Request shape for creating or updating an Azure Blob Storage batch-export destination.
 */
export interface AzureBlobDestinationRequestApi {
    type: AzureBlobDestinationRequestApiType
    /** ID of an azure-blob-kind Integration. Use the integrations-list MCP tool to find one. */
    integration_id: number
    config: AzureBlobDestinationConfigApi
}

export type BatchExportDestinationRequestApi = DatabricksDestinationRequestApi | AzureBlobDestinationRequestApi

/**
 * Request body for create/partial_update on BatchExportViewSet.

Mirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic
`destination` schema so integration_id is marked required on the types that need
it. Responses continue to use `BatchExportSerializer`.
 */
export interface BatchExportRequestApi {
    /** Human-readable name for the batch export. */
    name: string
    /** Which data model to export (events, persons, sessions).

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions */
    model?: ModelEnumApi
    /** Destination configuration. Required integration_id is enforced per destination type. */
    destination: BatchExportDestinationRequestApi
    /** How often the batch export should run.

* `hour` - hour
* `day` - day
* `week` - week
* `every 5 minutes` - every 5 minutes
* `every 15 minutes` - every 15 minutes */
    interval: IntervalEnumApi
    /** Whether the batch export is paused. */
    paused?: boolean
    /** Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases. */
    hogql_query?: string
    filters?: unknown | null
    /**
     * IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries.
     * @nullable
     */
    timezone?: string | null
    /**
     * Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).
     * @minimum 0
     * @maximum 6
     * @nullable
     */
    offset_day?: number | null
    /**
     * Hour-of-day offset (0-23) for daily and weekly intervals.
     * @minimum 0
     * @maximum 23
     * @nullable
     */
    offset_hour?: number | null
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

/**
 * @nullable
 */
export type BatchExportBackfillApiProgress = {
    /** @nullable */
    readonly total_runs?: number | null
    /** @nullable */
    readonly finished_runs?: number | null
    /** @nullable */
    readonly progress?: number | null
} | null | null

export interface BatchExportBackfillApi {
    readonly id: string
    /** @nullable */
    readonly progress: BatchExportBackfillApiProgress
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
    /**
     * The total number of records to export. Initially estimated, updated with actual count after completion.
     * @minimum -2147483648
     * @maximum 2147483647
     * @nullable
     */
    total_records_count?: number | null
    /**
     * The actual start time after adjustment for earliest available data. May differ from start_at if user requested a date before data exists.
     * @nullable
     */
    adjusted_start_at?: string | null
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
 * Request body for create/partial_update on BatchExportViewSet.

Mirrors the writeable fields of `BatchExportSerializer` but uses a polymorphic
`destination` schema so integration_id is marked required on the types that need
it. Responses continue to use `BatchExportSerializer`.
 */
export interface PatchedBatchExportRequestApi {
    /** Human-readable name for the batch export. */
    name?: string
    /** Which data model to export (events, persons, sessions).

* `events` - Events
* `persons` - Persons
* `sessions` - Sessions */
    model?: ModelEnumApi
    /** Destination configuration. Required integration_id is enforced per destination type. */
    destination?: BatchExportDestinationRequestApi
    /** How often the batch export should run.

* `hour` - hour
* `day` - day
* `week` - week
* `every 5 minutes` - every 5 minutes
* `every 15 minutes` - every 15 minutes */
    interval?: IntervalEnumApi
    /** Whether the batch export is paused. */
    paused?: boolean
    /** Optional HogQL SELECT defining a custom model schema. Only recommended in advanced use cases. */
    hogql_query?: string
    filters?: unknown | null
    /**
     * IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC') controlling daily and weekly interval boundaries.
     * @nullable
     */
    timezone?: string | null
    /**
     * Day-of-week offset for weekly intervals (0=Sunday, 6=Saturday).
     * @minimum 0
     * @maximum 6
     * @nullable
     */
    offset_day?: number | null
    /**
     * Hour-of-day offset (0-23) for daily and weekly intervals.
     * @minimum 0
     * @maximum 23
     * @nullable
     */
    offset_hour?: number | null
}

/**
 * * `Databricks` - Databricks
 */
export type DatabricksDestinationRequestTypeEnumApi =
    (typeof DatabricksDestinationRequestTypeEnumApi)[keyof typeof DatabricksDestinationRequestTypeEnumApi]

export const DatabricksDestinationRequestTypeEnumApi = {
    Databricks: 'Databricks',
} as const

/**
 * * `AzureBlob` - AzureBlob
 */
export type AzureBlobDestinationRequestTypeEnumApi =
    (typeof AzureBlobDestinationRequestTypeEnumApi)[keyof typeof AzureBlobDestinationRequestTypeEnumApi]

export const AzureBlobDestinationRequestTypeEnumApi = {
    AzureBlob: 'AzureBlob',
} as const

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

export type BatchExportsRunsLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}

export type BatchExportsLogsRetrieveParams = {
    /**
     * Only return entries after this ISO 8601 timestamp.
     */
    after?: string
    /**
     * Only return entries before this ISO 8601 timestamp.
     */
    before?: string
    /**
     * Filter logs to a specific execution instance.
     * @minLength 1
     */
    instance_id?: string
    /**
     * Comma-separated log levels to include, e.g. 'WARN,ERROR'. Valid levels: DEBUG, LOG, INFO, WARN, ERROR.
     * @minLength 1
     */
    level?: string
    /**
     * Maximum number of log entries to return (1-500, default 50).
     * @minimum 1
     * @maximum 500
     */
    limit?: number
    /**
     * Case-insensitive substring search across log messages.
     * @minLength 1
     */
    search?: string
}
