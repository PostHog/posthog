// Assuming this path is correct from your initial file
import { HogFunctionTemplate } from '~/cdp/types'

interface DestinationConfig {
    name: string
    id: string
    icon_url: string
    category: string[]
}

// This array will contain your definitions.
// 'description' is NOT included here as it will be generated.
const destinationDefinitions: DestinationConfig[] = [
    // A/B Testing & Feature Experimentation
    {
        name: 'Apptimize',
        id: 'coming-soon-apptimize',
        icon_url: '/static/coming-soon-destinations/Apptimize.png',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Candu',
        id: 'coming-soon-candu',
        icon_url: '/static/coming-soon-destinations/Candu.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'ConvertFlow',
        id: 'coming-soon-convertflow',
        icon_url: '/static/coming-soon-destinations/ConvertFlow.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Google Optimize',
        id: 'coming-soon-google-optimize',
        icon_url: '/static/coming-soon-destinations/Google_Optimize.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Monetate',
        id: 'coming-soon-monetate',
        icon_url: '/static/coming-soon-destinations/Monetate.png',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Ninetailed',
        id: 'coming-soon-ninetailed',
        icon_url: '/static/coming-soon-destinations/Ninetailed.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Split',
        id: 'coming-soon-split',
        icon_url: '/static/coming-soon-destinations/Split.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Statsig',
        id: 'coming-soon-statsig',
        icon_url: '/static/coming-soon-destinations/Statsig.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },
    {
        name: 'Taplytics',
        id: 'coming-soon-taplytics',
        icon_url: '/static/coming-soon-destinations/Taplytics.svg',
        category: ['A/B Testing & Feature Experimentation'],
    },

    // Advertising
    {
        name: 'AdRoll',
        id: 'coming-soon-adroll',
        icon_url: '/static/coming-soon-destinations/AdRoll.svg',
        category: ['Advertising'],
    },
    {
        name: 'Bing Ads',
        id: 'coming-soon-bing-ads',
        icon_url: '/static/coming-soon-destinations/Bing_Ads.svg',
        category: ['Advertising'],
    },
    {
        name: 'Criteo',
        id: 'coming-soon-criteo',
        icon_url: '/static/coming-soon-destinations/Criteo.svg',
        category: ['Advertising'],
    },
    {
        name: 'Criteo Audience',
        id: 'coming-soon-criteo-audience',
        icon_url: '/static/coming-soon-destinations/Criteo_Audience.svg',
        category: ['Advertising'],
    },
    {
        name: 'Quora',
        id: 'coming-soon-quora',
        icon_url: '/static/coming-soon-destinations/Quora.svg',
        category: ['Advertising'],
    },
    {
        name: 'Spotify Pixel',
        id: 'coming-soon-spotify-pixel',
        icon_url: '/static/coming-soon-destinations/Spotify_Pixel.svg',
        category: ['Advertising'],
    },
    {
        name: 'Tradedesk',
        id: 'coming-soon-tradedesk',
        icon_url: '/static/coming-soon-destinations/Tradedesk.svg',
        category: ['Advertising'],
    },
    {
        name: 'Tradedesk Audience',
        id: 'coming-soon-tradedesk-audience',
        icon_url: '/static/coming-soon-destinations/Tradedesk_Audience.svg',
        category: ['Advertising'],
    },
    {
        name: 'X Ads',
        id: 'coming-soon-x-ads',
        icon_url: '/static/coming-soon-destinations/X_Ads.svg',
        category: ['Advertising'],
    },

    // Analytics
    {
        name: 'AdLearn',
        id: 'coming-soon-adlearn',
        icon_url: '/static/coming-soon-destinations/AdLearn.png',
        category: ['Analytics'],
    },
    {
        name: 'Adobe Analytics',
        id: 'coming-soon-adobe-analytics',
        icon_url: '/static/coming-soon-destinations/Adobe_Analytics.png',
        category: ['Analytics'],
    },
    {
        name: 'Amazon Personalize',
        id: 'coming-soon-amazon-personalize',
        icon_url: '/static/coming-soon-destinations/Amazon_Personalize.svg',
        category: ['Analytics'],
    },
    {
        name: 'Chartbeat',
        id: 'coming-soon-chartbeat',
        icon_url: '/static/coming-soon-destinations/Chartbeat.png',
        category: ['Analytics'],
    },
    {
        name: 'Comscore',
        id: 'coming-soon-comscore',
        icon_url: '/static/coming-soon-destinations/Comscore.svg',
        category: ['Analytics'],
    },
    {
        name: 'CrowdPower',
        id: 'coming-soon-crowdpower',
        icon_url: '/static/coming-soon-destinations/CrowdPower.svg',
        category: ['Analytics'],
    },
    {
        name: 'Cruncher',
        id: 'coming-soon-cruncher',
        icon_url: '/static/coming-soon-destinations/Cruncher.svg',
        category: ['Analytics'],
    },
    {
        name: 'CustomFit.ai',
        id: 'coming-soon-customfit-ai',
        icon_url: '/static/coming-soon-destinations/CustomFit.ai.png',
        category: ['Analytics'],
    },
    {
        name: 'Firebase',
        id: 'coming-soon-firebase',
        icon_url: '/static/coming-soon-destinations/Firebase.svg',
        category: ['Analytics'],
    },
    {
        name: 'Flurry',
        id: 'coming-soon-flurry',
        icon_url: '/static/coming-soon-destinations/Flurry.svg',
        category: ['Analytics'],
    },
    {
        name: 'Google Analytics 4',
        id: 'coming-soon-google-analytics-4',
        icon_url: '/static/coming-soon-destinations/Google_Analytics_4.svg',
        category: ['Analytics'],
    },
    {
        name: 'Hotjar',
        id: 'coming-soon-hotjar',
        icon_url: '/static/coming-soon-destinations/Hotjar.svg',
        category: ['Analytics'],
    },
    {
        name: 'Indicative Analytics',
        id: 'coming-soon-indicative-analytics',
        icon_url: '/static/coming-soon-destinations/Indicative_Analytics.webp',
        category: ['Analytics'],
    },
    {
        name: 'Keen.io',
        id: 'coming-soon-keen-io',
        icon_url: '/static/coming-soon-destinations/Keen.io.png',
        category: ['Analytics'],
    },
    {
        name: 'Kissmetrics',
        id: 'coming-soon-kissmetrics',
        icon_url: '/static/coming-soon-destinations/Kissmetrics.svg',
        category: ['Analytics'],
    },
    {
        name: 'Kubit',
        id: 'coming-soon-kubit',
        icon_url: '/static/coming-soon-destinations/Kubit.svg',
        category: ['Analytics'],
    },
    {
        name: 'Lytics',
        id: 'coming-soon-lytics',
        icon_url: '/static/coming-soon-destinations/Lytics.svg',
        category: ['Analytics'],
    },
    {
        name: 'Mode Analytics',
        id: 'coming-soon-mode-analytics',
        icon_url: '/static/coming-soon-destinations/Mode_Analytics.svg',
        category: ['Analytics'],
    },
    {
        name: 'Moesif API Analytics',
        id: 'coming-soon-moesif-api-analytics',
        icon_url: '/static/coming-soon-destinations/Moesif_API_Analytics.svg',
        category: ['Analytics'],
    },
    {
        name: 'Parse.ly',
        id: 'coming-soon-parse-ly',
        icon_url: '/static/coming-soon-destinations/Parse.ly.svg',
        category: ['Analytics'],
    },
    {
        name: 'Pendo',
        id: 'coming-soon-pendo',
        icon_url: '/static/coming-soon-destinations/Pendo.png',
        category: ['Analytics'],
    },
    {
        name: 'ProfitWell',
        id: 'coming-soon-profitwell',
        icon_url: '/static/coming-soon-destinations/ProfitWell.png',
        category: ['Analytics'],
    },
    {
        name: 'Quantum Metric',
        id: 'coming-soon-quantum-metric',
        icon_url: '/static/coming-soon-destinations/Quantum_Metric.svg',
        category: ['Analytics'],
    },
    {
        name: 'Redash',
        id: 'coming-soon-redash',
        icon_url: '/static/coming-soon-destinations/Redash.svg',
        category: ['Analytics'],
    },
    {
        name: 'Serenytics',
        id: 'coming-soon-serenytics',
        icon_url: '/static/coming-soon-destinations/Serenytics.svg',
        category: ['Analytics'],
    },
    {
        name: 'Shynet',
        id: 'coming-soon-shynet',
        icon_url: '/static/coming-soon-destinations/Shynet.svg',
        category: ['Analytics'],
    },
    {
        name: 'Tableau',
        id: 'coming-soon-tableau',
        icon_url: '/static/coming-soon-destinations/Tableau.svg',
        category: ['Analytics'],
    },
    {
        name: 'Woopra',
        id: 'coming-soon-woopra',
        icon_url: '/static/coming-soon-destinations/Woopra.svg',
        category: ['Analytics'],
    },
    {
        name: 'Youbora',
        id: 'coming-soon-youbora',
        icon_url: '/static/coming-soon-destinations/Youbora.png',
        category: ['Analytics'],
    },

    // Attribution Platforms
    {
        name: 'Adjust',
        id: 'coming-soon-adjust',
        icon_url: '/static/coming-soon-destinations/Adjust.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'AppsFlyer',
        id: 'coming-soon-appsflyer',
        icon_url: '/static/coming-soon-destinations/AppsFlyer.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Attribution',
        id: 'coming-soon-attribution',
        icon_url: '/static/coming-soon-destinations/Attribution.png',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Branch',
        id: 'coming-soon-branch',
        icon_url: '/static/coming-soon-destinations/Branch.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Kochava',
        id: 'coming-soon-kochava',
        icon_url: '/static/coming-soon-destinations/Kochava.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Lotame',
        id: 'coming-soon-lotame',
        icon_url: '/static/coming-soon-destinations/Lotame.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Nielsen DCR',
        id: 'coming-soon-nielsen-dcr',
        icon_url: '/static/coming-soon-destinations/Nielsen_DCR.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Rockerbox',
        id: 'coming-soon-rockerbox',
        icon_url: '/static/coming-soon-destinations/Rockerbox.svg',
        category: ['Attribution Platforms'],
    },
    {
        name: 'TVSquared',
        id: 'coming-soon-tvsquared',
        icon_url: '/static/coming-soon-destinations/TVSquared.png',
        category: ['Attribution Platforms'],
    },
    {
        name: 'Tapstream',
        id: 'coming-soon-tapstream',
        icon_url: '/static/coming-soon-destinations/Tapstream.png',
        category: ['Attribution Platforms'],
    },

    // Authentication Platforms
    {
        name: 'Castle',
        id: 'coming-soon-castle',
        icon_url: '/static/coming-soon-destinations/Castle.svg',
        category: ['Authentication Platforms'],
    },
    {
        name: 'TrafficGuard',
        id: 'coming-soon-trafficguard',
        icon_url: '/static/coming-soon-destinations/TrafficGuard.svg',
        category: ['Authentication Platforms'],
    },

    // Automation
    {
        name: 'PipeDream',
        id: 'coming-soon-pipedream',
        icon_url: '/static/coming-soon-destinations/PipeDream.svg',
        category: ['Automation'],
    },
    {
        name: 'Tray.io',
        id: 'coming-soon-tray-io',
        icon_url: '/static/coming-soon-destinations/Tray.io.svg',
        category: ['Automation'],
    },

    // Business Messaging
    {
        name: 'Drift',
        id: 'coming-soon-drift',
        icon_url: '/static/coming-soon-destinations/Drift.png',
        category: ['Business Messaging'],
    },
    {
        name: 'SnapEngage',
        id: 'coming-soon-snapengage',
        icon_url: '/static/coming-soon-destinations/SnapEngage.png',
        category: ['Business Messaging'],
    },
    {
        name: 'User.com',
        id: 'coming-soon-user-com',
        icon_url: '/static/coming-soon-destinations/User.com.svg',
        category: ['Business Messaging'],
    },

    // CRM
    {
        name: 'Custify',
        id: 'coming-soon-custify',
        icon_url: '/static/coming-soon-destinations/Custify.svg',
        category: ['CRM'],
    },
    {
        name: 'Emarsys',
        id: 'coming-soon-emarsys',
        icon_url: '/static/coming-soon-destinations/Emarsys.svg',
        category: ['CRM'],
    },
    {
        name: 'Freshsales',
        id: 'coming-soon-freshsales',
        icon_url: '/static/coming-soon-destinations/Freshsales.svg',
        category: ['CRM'],
    },
    {
        name: 'Variance',
        id: 'coming-soon-variance',
        icon_url: '/static/coming-soon-destinations/Variance.webp',
        category: ['CRM'],
    },

    // Consent Management Platform
    {
        name: 'Axeptio',
        id: 'coming-soon-axeptio',
        icon_url: '/static/coming-soon-destinations/Axeptio.svg',
        category: ['Consent Management Platform'],
    },

    // Customer Data Platforms
    {
        name: 'Amperity',
        id: 'coming-soon-amperity',
        icon_url: '/static/coming-soon-destinations/Amperity_.svg',
        category: ['Customer Data Platforms'],
    },
    {
        name: 'Hull',
        id: 'coming-soon-hull',
        icon_url: '/static/coming-soon-destinations/Hull.svg',
        category: ['Customer Data Platforms'],
    },

    // Customer Service
    {
        name: 'Aircall',
        id: 'coming-soon-aircall',
        icon_url: '/static/coming-soon-destinations/Aircall.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Callingly',
        id: 'coming-soon-callingly',
        icon_url: '/static/coming-soon-destinations/Callingly.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Elevio',
        id: 'coming-soon-elevio',
        icon_url: '/static/coming-soon-destinations/Elevio.png',
        category: ['Customer Service'],
    },
    {
        name: 'Gladly',
        id: 'coming-soon-gladly',
        icon_url: '/static/coming-soon-destinations/Gladly.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Help Scout',
        id: 'coming-soon-help-scout',
        icon_url: '/static/coming-soon-destinations/Help_Scout.svg',
        category: ['Customer Service'],
    },
    {
        name: 'InMoment',
        id: 'coming-soon-inmoment',
        icon_url: '/static/coming-soon-destinations/InMoment.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Kustomer',
        id: 'coming-soon-kustomer',
        icon_url: '/static/coming-soon-destinations/Kustomer.svg',
        category: ['Customer Service'],
    },
    {
        name: 'LiveChat',
        id: 'coming-soon-livechat',
        icon_url: '/static/coming-soon-destinations/LiveChat.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Olark',
        id: 'coming-soon-olark',
        icon_url: '/static/coming-soon-destinations/Olark.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Qualaroo',
        id: 'coming-soon-qualaroo',
        icon_url: '/static/coming-soon-destinations/Qualaroo.png',
        category: ['Customer Service'],
    },
    {
        name: 'Refiner',
        id: 'coming-soon-refiner',
        icon_url: '/static/coming-soon-destinations/Refiner.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Salesmachine',
        id: 'coming-soon-salesmachine',
        icon_url: '/static/coming-soon-destinations/Salesmachine.png',
        category: ['Customer Service'],
    },
    {
        name: 'SatisMeter',
        id: 'coming-soon-satismeter',
        icon_url: '/static/coming-soon-destinations/SatisMeter.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Trengo',
        id: 'coming-soon-trengo',
        icon_url: '/static/coming-soon-destinations/Trengo.svg',
        category: ['Customer Service'],
    },
    {
        name: 'UserVoice',
        id: 'coming-soon-uservoice',
        icon_url: '/static/coming-soon-destinations/UserVoice.svg',
        category: ['Customer Service'],
    },
    {
        name: 'Wootric',
        id: 'coming-soon-wootric',
        icon_url: '/static/coming-soon-destinations/Wootric.png',
        category: ['Customer Service'],
    },

    // Data Ingestion
    {
        name: 'Amazon Event Bridge',
        id: 'coming-soon-amazon-event-bridge',
        icon_url: '/static/coming-soon-destinations/Amazon_Event_Bridge.png',
        category: ['Data Ingestion'],
    },
    {
        name: 'Apache Kafka',
        id: 'coming-soon-apache-kafka',
        icon_url: '/static/coming-soon-destinations/Apache_Kafka_.svg',
        category: ['Data Ingestion'],
    },
    {
        name: 'Azure Event Hubs',
        id: 'coming-soon-azure-event-hubs',
        icon_url: '/static/coming-soon-destinations/Azure_Event_Hubs.svg',
        category: ['Data Ingestion'],
    },

    // Data Warehouse
    {
        name: 'Azure Data Lake',
        id: 'coming-soon-azure-data-lake',
        icon_url: '/static/coming-soon-destinations/Azure_Data_Lake.svg',
        category: ['Data Warehouse'],
    },
    {
        name: 'Databricks Delta Lake',
        id: 'coming-soon-databricks-delta-lake',
        icon_url: '/static/coming-soon-destinations/Databricks_Delta_Lake.svg',
        category: ['Data Warehouse'],
    },
    {
        name: 'IBM DB2 Data Warehouse',
        id: 'coming-soon-ibm-db2-data-warehouse',
        icon_url: '/static/coming-soon-destinations/IBM_DB2_Data_Warehouse.png',
        category: ['Data Warehouse'],
    },
    {
        name: 'Materialize',
        id: 'coming-soon-materialize',
        icon_url: '/static/coming-soon-destinations/Materialize.svg',
        category: ['Data Warehouse'],
    },
    {
        name: 'Microsoft Azure SQL Data Warehouse',
        id: 'coming-soon-microsoft-azure-sql-data-warehouse',
        icon_url: '/static/coming-soon-destinations/Microsoft_Azure_SQL_Data_Warehouse.svg',
        category: ['Data Warehouse'],
    },
    {
        name: 'Microsoft Azure Synapse Analytics',
        id: 'coming-soon-microsoft-azure-synapse-analytics',
        icon_url: '/static/coming-soon-destinations/Microsoft_Azure_Synapse_Analytics.svg',
        category: ['Data Warehouse'],
    },

    // Databases & Object Storage
    {
        name: 'Azure Blob Storage',
        id: 'coming-soon-azure-blob-storage',
        icon_url: '/static/coming-soon-destinations/Azure_Blob_Storage.svg',
        category: ['Databases & Object Storage'],
    },
    {
        name: 'DigitalOcean Spaces',
        id: 'coming-soon-digitalocean-spaces',
        icon_url: '/static/coming-soon-destinations/DigitalOcean_Spaces.svg',
        category: ['Databases & Object Storage'],
    },
    {
        name: 'JackDB',
        id: 'coming-soon-jackdb',
        icon_url: '/static/coming-soon-destinations/JackDB.png',
        category: ['Databases & Object Storage'],
    },
    {
        name: 'MS SQL Server',
        id: 'coming-soon-ms-sql-server',
        icon_url: '/static/coming-soon-destinations/MS_SQL_Server.png',
        category: ['Databases & Object Storage'],
    },
    {
        name: 'MinIO',
        id: 'coming-soon-minio',
        icon_url: '/static/coming-soon-destinations/MinIO.svg',
        category: ['Databases & Object Storage'],
    },

    // DevOps
    {
        name: 'App Center',
        id: 'coming-soon-app-center',
        icon_url: '/static/coming-soon-destinations/App_Center.png',
        category: ['DevOps'],
    },

    // ETL Platforms
    {
        name: 'Stitch Data',
        id: 'coming-soon-stitch-data',
        icon_url: '/static/coming-soon-destinations/Stitch_Data.svg',
        category: ['ETL Platforms'],
    },

    // Error Reporting & Monitoring
    {
        name: 'BugSnag',
        id: 'coming-soon-bugsnag',
        icon_url: '/static/coming-soon-destinations/BugSnag.svg',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'Errorception',
        id: 'coming-soon-errorception',
        icon_url: '/static/coming-soon-destinations/Errorception.png',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'New Relic',
        id: 'coming-soon-new-relic',
        icon_url: '/static/coming-soon-destinations/New_Relic.svg',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'Pingdom',
        id: 'coming-soon-pingdom',
        icon_url: '/static/coming-soon-destinations/Pingdom.svg',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'Rollbar',
        id: 'coming-soon-rollbar',
        icon_url: '/static/coming-soon-destinations/Rollbar.svg',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'Sentry',
        id: 'coming-soon-sentry',
        icon_url: '/static/coming-soon-destinations/Sentry.svg',
        category: ['Error Reporting & Monitoring'],
    },
    {
        name: 'TrackJS',
        id: 'coming-soon-trackjs',
        icon_url: '/static/coming-soon-destinations/TrackJS.svg',
        category: ['Error Reporting & Monitoring'],
    },

    // Event Messaging
    {
        name: 'Confluent Cloud',
        id: 'coming-soon-confluent-cloud',
        icon_url: '/static/coming-soon-destinations/Confluent_Cloud.svg',
        category: ['Event Messaging'],
    },

    // Heatmap Recording
    {
        name: 'Crazy Egg',
        id: 'coming-soon-crazy-egg',
        icon_url: '/static/coming-soon-destinations/Crazy_Egg.svg',
        category: ['Heatmap Recording'],
    },
    {
        name: 'Inspectlet',
        id: 'coming-soon-inspectlet',
        icon_url: '/static/coming-soon-destinations/Inspectlet_.svg',
        category: ['Heatmap Recording'],
    },
    {
        name: 'Lucky Orange',
        id: 'coming-soon-lucky-orange',
        icon_url: '/static/coming-soon-destinations/Lucky_Orange.png',
        category: ['Heatmap Recording'],
    },
    {
        name: 'MouseStats',
        id: 'coming-soon-mousestats',
        icon_url: '/static/coming-soon-destinations/MouseStats.png',
        category: ['Heatmap Recording'],
    },
    {
        name: 'Mouseflow',
        id: 'coming-soon-mouseflow',
        icon_url: '/static/coming-soon-destinations/Mouseflow.svg',
        category: ['Heatmap Recording'],
    },

    // Incident Management
    {
        name: 'SIGNL4',
        id: 'coming-soon-signl4',
        icon_url: '/static/coming-soon-destinations/SIGNL4.svg',
        category: ['Incident Management'],
    },

    // Marketing
    {
        name: 'Ambassador',
        id: 'coming-soon-ambassador',
        icon_url: '/static/coming-soon-destinations/Ambassador.svg',
        category: ['Marketing'],
    },
    {
        name: 'Awin',
        id: 'coming-soon-awin',
        icon_url: '/static/coming-soon-destinations/Awin.svg',
        category: ['Marketing'],
    },
    {
        name: 'Bluecore',
        id: 'coming-soon-bluecore',
        icon_url: '/static/coming-soon-destinations/Bluecore.png',
        category: ['Marketing'],
    },
    {
        name: 'Blueshift',
        id: 'coming-soon-blueshift',
        icon_url: '/static/coming-soon-destinations/Blueshift.svg',
        category: ['Marketing'],
    },
    {
        name: 'Commandbar',
        id: 'coming-soon-commandbar',
        icon_url: '/static/coming-soon-destinations/Commandbar.svg',
        category: ['Marketing'],
    },
    {
        name: 'Courier',
        id: 'coming-soon-courier',
        icon_url: '/static/coming-soon-destinations/Courier.svg',
        category: ['Marketing'],
    },
    {
        name: 'Eloqua',
        id: 'coming-soon-eloqua',
        icon_url: '/static/coming-soon-destinations/Eloqua.svg',
        category: ['Marketing'],
    },
    {
        name: 'Extole',
        id: 'coming-soon-extole',
        icon_url: '/static/coming-soon-destinations/Extole.svg',
        category: ['Marketing'],
    },
    {
        name: 'Freshmarketer',
        id: 'coming-soon-freshmarketer',
        icon_url: '/static/coming-soon-destinations/Freshmarketer.svg',
        category: ['Marketing'],
    },
    {
        name: 'Friendbuy',
        id: 'coming-soon-friendbuy',
        icon_url: '/static/coming-soon-destinations/Friendbuy.svg',
        category: ['Marketing'],
    },
    {
        name: 'FunnelEnvy',
        id: 'coming-soon-funnelenvy',
        icon_url: '/static/coming-soon-destinations/FunnelEnvy.png',
        category: ['Marketing'],
    },
    {
        name: 'Gainsight CS',
        id: 'coming-soon-gainsight-cs',
        icon_url: '/static/coming-soon-destinations/Gainsight_CS.png',
        category: ['Marketing'],
    },
    {
        name: 'GoSquared',
        id: 'coming-soon-gosquared',
        icon_url: '/static/coming-soon-destinations/GoSquared.png',
        category: ['Marketing'],
    },
    {
        name: 'Lemnisk',
        id: 'coming-soon-lemnisk',
        icon_url: '/static/coming-soon-destinations/Lemnisk.svg',
        category: ['Marketing'],
    },
    {
        name: 'Madkudu',
        id: 'coming-soon-madkudu',
        icon_url: '/static/coming-soon-destinations/Madkudu.svg',
        category: ['Marketing'],
    },
    {
        name: 'Mailmodo',
        id: 'coming-soon-mailmodo',
        icon_url: '/static/coming-soon-destinations/Mailmodo.svg',
        category: ['Marketing'],
    },
    {
        name: 'Marketo',
        id: 'coming-soon-marketo',
        icon_url: '/static/coming-soon-destinations/Marketo.svg',
        category: ['Marketing'],
    },
    {
        name: 'Marketo Lead Import',
        id: 'coming-soon-marketo-lead-import',
        icon_url: '/static/coming-soon-destinations/Marketo_Lead_Import.svg',
        category: ['Marketing'],
    },
    {
        name: 'Mautic',
        id: 'coming-soon-mautic',
        icon_url: '/static/coming-soon-destinations/Mautic.svg',
        category: ['Marketing'],
    },
    {
        name: 'Ometria',
        id: 'coming-soon-ometria',
        icon_url: '/static/coming-soon-destinations/Ometria.svg',
        category: ['Marketing'],
    },
    {
        name: 'OneSignal',
        id: 'coming-soon-onesignal',
        icon_url: '/static/coming-soon-destinations/OneSignal.svg',
        category: ['Marketing'],
    },
    {
        name: 'Ortto (Autopilot)',
        id: 'coming-soon-ortto-autopilot',
        icon_url: '/static/coming-soon-destinations/Ortto_Autopilot_.svg',
        category: ['Marketing'],
    },
    {
        name: 'PersistIQ Cloud Mode',
        id: 'coming-soon-persistiq-cloud-mode',
        icon_url: '/static/coming-soon-destinations/PersistIQ_Cloud_Mode.svg',
        category: ['Marketing'],
    },
    {
        name: 'Post Affiliate Pro',
        id: 'coming-soon-post-affiliate-pro',
        icon_url: '/static/coming-soon-destinations/Post_Affiliate_Pro.svg',
        category: ['Marketing'],
    },
    {
        name: 'Qualtrics Website Feedback',
        id: 'coming-soon-qualtrics-website-feedback',
        icon_url: '/static/coming-soon-destinations/Qualtrics_Website_Feedback.svg',
        category: ['Marketing'],
    },
    {
        name: 'Rakuten',
        id: 'coming-soon-rakuten',
        icon_url: '/static/coming-soon-destinations/Rakuten.svg',
        category: ['Marketing'],
    },
    {
        name: 'Refersion',
        id: 'coming-soon-refersion',
        icon_url: '/static/coming-soon-destinations/Refersion.svg',
        category: ['Marketing'],
    },
    {
        name: 'SaaSquatch',
        id: 'coming-soon-saasquatch',
        icon_url: '/static/coming-soon-destinations/SaaSquatch.svg',
        category: ['Marketing'],
    },
    {
        name: 'Salesforce Marketing Cloud',
        id: 'coming-soon-salesforce-marketing-cloud',
        icon_url: '/static/coming-soon-destinations/Salesforce_Marketing_Cloud.svg',
        category: ['Marketing'],
    },
    {
        name: 'Salesforce Pardot',
        id: 'coming-soon-salesforce-pardot',
        icon_url: '/static/coming-soon-destinations/Salesforce_Pardot.svg',
        category: ['Marketing'],
    },
    {
        name: 'Singular',
        id: 'coming-soon-singular',
        icon_url: '/static/coming-soon-destinations/Singular.svg',
        category: ['Marketing'],
    },
    {
        name: 'Talkable',
        id: 'coming-soon-talkable',
        icon_url: '/static/coming-soon-destinations/Talkable.svg',
        category: ['Marketing'],
    },
    {
        name: 'Tune',
        id: 'coming-soon-tune',
        icon_url: '/static/coming-soon-destinations/Tune.svg',
        category: ['Marketing'],
    },
    {
        name: 'Userlist',
        id: 'coming-soon-userlist',
        icon_url: '/static/coming-soon-destinations/Userlist.png',
        category: ['Marketing'],
    },
    {
        name: 'Vero',
        id: 'coming-soon-vero',
        icon_url: '/static/coming-soon-destinations/Vero.svg',
        category: ['Marketing'],
    },
    {
        name: 'Vitally',
        id: 'coming-soon-vitally',
        icon_url: '/static/coming-soon-destinations/Vitally.svg',
        category: ['Marketing'],
    },

    // Productivity
    {
        name: 'Google Sheets',
        id: 'coming-soon-google-sheets',
        icon_url: '/static/coming-soon-destinations/Google_Sheets.svg',
        category: ['Productivity'],
    },
    {
        name: 'Monday',
        id: 'coming-soon-monday',
        icon_url: '/static/coming-soon-destinations/Monday.svg',
        category: ['Productivity'],
    },

    // Serverless
    {
        name: 'AWS Lambda',
        id: 'coming-soon-aws-lambda',
        icon_url: '/static/coming-soon-destinations/AWS_Lambda.svg',
        category: ['Serverless'],
    },
    {
        name: 'Google Cloud Functions',
        id: 'coming-soon-google-cloud-functions',
        icon_url: '/static/coming-soon-destinations/Google_Cloud_Functions.svg',
        category: ['Serverless'],
    },
    {
        name: 'Iron.io',
        id: 'coming-soon-iron-io',
        icon_url: '/static/coming-soon-destinations/Iron.io_.svg',
        category: ['Serverless'],
    },

    // Streaming Platforms
    {
        name: 'Roku',
        id: 'coming-soon-roku',
        icon_url: '/static/coming-soon-destinations/Roku.svg',
        category: ['Streaming Platforms'],
    },

    // Surveys
    {
        name: 'Delighted',
        id: 'coming-soon-delighted',
        icon_url: '/static/coming-soon-destinations/Delighted.svg',
        category: ['Surveys'],
    },
    {
        name: 'Promoter.io',
        id: 'coming-soon-promoter-io',
        icon_url: '/static/coming-soon-destinations/Promoter.io.png',
        category: ['Surveys'],
    },

    // User Engagement Platforms
    {
        name: 'Appcues',
        id: 'coming-soon-appcues',
        icon_url: '/static/coming-soon-destinations/Appcues.svg',
        category: ['User Engagement Platforms'],
    },
    {
        name: 'Leanplum',
        id: 'coming-soon-leanplum',
        icon_url: '/static/coming-soon-destinations/Leanplum.svg',
        category: ['User Engagement Platforms'],
    },
    {
        name: 'MoEngage',
        id: 'coming-soon-moengage',
        icon_url: '/static/coming-soon-destinations/MoEngage.svg',
        category: ['User Engagement Platforms'],
    },
    {
        name: 'WebEngage',
        id: 'coming-soon-webengage',
        icon_url: '/static/coming-soon-destinations/WebEngage.png',
        category: ['User Engagement Platforms'],
    },
]

// Use .map() to generate the full HogFunctionTemplate objects
// The common properties are now defined directly within the map.
export const allComingSoonTemplates: HogFunctionTemplate[] = destinationDefinitions.map((def) => ({
    ...def,
    description: `Send events to ${def.name}.`,
    free: true,
    status: 'coming_soon' as const,
    type: 'destination' as const,
    code: `return event;`,
    code_language: 'javascript',
    inputs_schema: [],
}))
