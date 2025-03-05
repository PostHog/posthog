from posthog.schema import SupportedCurrencies

# This is a list with all the currencies we support
#
# We don't support all currencies, because not all currencies are easy to collect data for
# both historically but also in our daily/hourly Dagster job collecting data from OXR.
#
# If you need a currency that's not in this list, you can add it to the list by
# updating `historical.csv` to include historical information about the new currency
# since January 1st 2000.
#
# You'll also need to update the Dagster job to start including that new currency,
# you might need to backfill data for that currency as well.
SUPPORTED_CURRENCIES: dict[SupportedCurrencies, str] = {
    SupportedCurrencies.AED: "United Arab Emirates Dirham",
    SupportedCurrencies.AFN: "Afghan Afghani",
    SupportedCurrencies.ALL: "Albanian Lek",
    SupportedCurrencies.AMD: "Armenian Dram",
    SupportedCurrencies.ANG: "Netherlands Antillean Guilder",
    SupportedCurrencies.AOA: "Angolan Kwanza",
    SupportedCurrencies.ARS: "Argentine Peso",
    SupportedCurrencies.AUD: "Australian Dollar",
    SupportedCurrencies.AWG: "Aruban Florin",
    SupportedCurrencies.AZN: "Azerbaijani Manat",
    SupportedCurrencies.BAM: "Bosnia-Herzegovina Convertible Mark",
    SupportedCurrencies.BBD: "Barbadian Dollar",
    SupportedCurrencies.BDT: "Bangladeshi Taka",
    SupportedCurrencies.BGN: "Bulgarian Lev",
    SupportedCurrencies.BHD: "Bahraini Dinar",
    SupportedCurrencies.BIF: "Burundian Franc",
    SupportedCurrencies.BMD: "Bermudan Dollar",
    SupportedCurrencies.BND: "Brunei Dollar",
    SupportedCurrencies.BOB: "Bolivian Boliviano",
    SupportedCurrencies.BRL: "Brazilian Real",
    SupportedCurrencies.BSD: "Bahamian Dollar",
    SupportedCurrencies.BTC: "Bitcoin",
    SupportedCurrencies.BTN: "Bhutanese Ngultrum",
    SupportedCurrencies.BWP: "Botswanan Pula",
    SupportedCurrencies.BYN: "Belarusian Ruble",
    SupportedCurrencies.BZD: "Belize Dollar",
    SupportedCurrencies.CAD: "Canadian Dollar",
    SupportedCurrencies.CDF: "Congolese Franc",
    SupportedCurrencies.CHF: "Swiss Franc",
    SupportedCurrencies.CLP: "Chilean Peso",
    SupportedCurrencies.CNY: "Chinese Yuan",
    SupportedCurrencies.COP: "Colombian Peso",
    SupportedCurrencies.CRC: "Costa Rican Colón",
    SupportedCurrencies.CVE: "Cape Verdean Escudo",
    SupportedCurrencies.CZK: "Czech Republic Koruna",
    SupportedCurrencies.DJF: "Djiboutian Franc",
    SupportedCurrencies.DKK: "Danish Krone",
    SupportedCurrencies.DOP: "Dominican Peso",
    SupportedCurrencies.DZD: "Algerian Dinar",
    SupportedCurrencies.EGP: "Egyptian Pound",
    SupportedCurrencies.ERN: "Eritrean Nakfa",
    SupportedCurrencies.ETB: "Ethiopian Birr",
    SupportedCurrencies.EUR: "Euro",
    SupportedCurrencies.FJD: "Fijian Dollar",
    SupportedCurrencies.GBP: "British Pound Sterling",
    SupportedCurrencies.GEL: "Georgian Lari",
    SupportedCurrencies.GHS: "Ghanaian Cedi",
    SupportedCurrencies.GIP: "Gibraltar Pound",
    SupportedCurrencies.GMD: "Gambian Dalasi",
    SupportedCurrencies.GNF: "Guinean Franc",
    SupportedCurrencies.GTQ: "Guatemalan Quetzal",
    SupportedCurrencies.GYD: "Guyanaese Dollar",
    SupportedCurrencies.HKD: "Hong Kong Dollar",
    SupportedCurrencies.HNL: "Honduran Lempira",
    SupportedCurrencies.HRK: "Croatian Kuna",  # Only available until Dec 31st 2022
    SupportedCurrencies.HTG: "Haitian Gourde",
    SupportedCurrencies.HUF: "Hungarian Forint",
    SupportedCurrencies.IDR: "Indonesian Rupiah",
    SupportedCurrencies.ILS: "Israeli New Sheqel",
    SupportedCurrencies.INR: "Indian Rupee",
    SupportedCurrencies.IQD: "Iraqi Dinar",
    SupportedCurrencies.IRR: "Iranian Rial",
    SupportedCurrencies.ISK: "Icelandic Króna",
    SupportedCurrencies.JMD: "Jamaican Dollar",
    SupportedCurrencies.JOD: "Jordanian Dinar",
    SupportedCurrencies.JPY: "Japanese Yen",
    SupportedCurrencies.KES: "Kenyan Shilling",
    SupportedCurrencies.KGS: "Kyrgystani Som",
    SupportedCurrencies.KHR: "Cambodian Riel",
    SupportedCurrencies.KMF: "Comorian Franc",
    SupportedCurrencies.KRW: "South Korean Won",
    SupportedCurrencies.KWD: "Kuwaiti Dinar",
    SupportedCurrencies.KYD: "Cayman Islands Dollar",
    SupportedCurrencies.KZT: "Kazakhstani Tenge",
    SupportedCurrencies.LAK: "Laotian Kip",
    SupportedCurrencies.LBP: "Lebanese Pound",
    SupportedCurrencies.LKR: "Sri Lankan Rupee",
    SupportedCurrencies.LRD: "Liberian Dollar",
    SupportedCurrencies.LTL: "Lithuanian Litas",  # Only available until Dec 31st 2014
    SupportedCurrencies.LVL: "Latvian Lats",  # Only available until Dec 31st 2013
    SupportedCurrencies.LSL: "Lesotho Loti",
    SupportedCurrencies.LYD: "Libyan Dinar",
    SupportedCurrencies.MAD: "Moroccan Dirham",
    SupportedCurrencies.MDL: "Moldovan Leu",
    SupportedCurrencies.MGA: "Malagasy Ariary",
    SupportedCurrencies.MKD: "Macedonian Denar",
    SupportedCurrencies.MMK: "Myanma Kyat",
    SupportedCurrencies.MNT: "Mongolian Tugrik",
    SupportedCurrencies.MOP: "Macanese Pataca",
    SupportedCurrencies.MRU: "Mauritanian Ouguiya",
    SupportedCurrencies.MTL: "Maltese Lira",  # Only available until Dec 31st 2007
    SupportedCurrencies.MUR: "Mauritian Rupee",
    SupportedCurrencies.MVR: "Maldivian Rufiyaa",
    SupportedCurrencies.MWK: "Malawian Kwacha",
    SupportedCurrencies.MXN: "Mexican Peso",
    SupportedCurrencies.MYR: "Malaysian Ringgit",
    SupportedCurrencies.MZN: "Mozambican Metical",
    SupportedCurrencies.NAD: "Namibian Dollar",
    SupportedCurrencies.NGN: "Nigerian Naira",
    SupportedCurrencies.NIO: "Nicaraguan Córdoba",
    SupportedCurrencies.NOK: "Norwegian Krone",
    SupportedCurrencies.NPR: "Nepalese Rupee",
    SupportedCurrencies.NZD: "New Zealand Dollar",
    SupportedCurrencies.OMR: "Omani Rial",
    SupportedCurrencies.PAB: "Panamanian Balboa",
    SupportedCurrencies.PEN: "Peruvian Nuevo Sol",
    SupportedCurrencies.PGK: "Papua New Guinean Kina",
    SupportedCurrencies.PHP: "Philippine Peso",
    SupportedCurrencies.PKR: "Pakistani Rupee",
    SupportedCurrencies.PLN: "Polish Zloty",
    SupportedCurrencies.PYG: "Paraguayan Guarani",
    SupportedCurrencies.QAR: "Qatari Rial",
    SupportedCurrencies.RON: "Romanian Leu",
    SupportedCurrencies.RSD: "Serbian Dinar",
    SupportedCurrencies.RUB: "Russian Ruble",
    SupportedCurrencies.RWF: "Rwandan Franc",
    SupportedCurrencies.SAR: "Saudi Riyal",
    SupportedCurrencies.SBD: "Solomon Islands Dollar",
    SupportedCurrencies.SCR: "Seychellois Rupee",
    SupportedCurrencies.SDG: "Sudanese Pound",
    SupportedCurrencies.SEK: "Swedish Krona",
    SupportedCurrencies.SGD: "Singapore Dollar",
    SupportedCurrencies.SRD: "Surinamese Dollar",
    SupportedCurrencies.SSP: "South Sudanese Pound",
    SupportedCurrencies.STN: "São Tomé and Príncipe Dobra",
    SupportedCurrencies.SYP: "Syrian Pound",
    SupportedCurrencies.SZL: "Swazi Lilangeni",
    SupportedCurrencies.THB: "Thai Baht",
    SupportedCurrencies.TJS: "Tajikistani Somoni",
    SupportedCurrencies.TMT: "Turkmenistani Manat",
    SupportedCurrencies.TND: "Tunisian Dinar",
    SupportedCurrencies.TOP: "Tongan Pa'anga",
    SupportedCurrencies.TRY: "Turkish Lira",
    SupportedCurrencies.TTD: "Trinidad and Tobago Dollar",
    SupportedCurrencies.TWD: "New Taiwan Dollar",
    SupportedCurrencies.TZS: "Tanzanian Shilling",
    SupportedCurrencies.UAH: "Ukrainian Hryvnia",
    SupportedCurrencies.UGX: "Ugandan Shilling",
    SupportedCurrencies.USD: "United States Dollar",
    SupportedCurrencies.UYU: "Uruguayan Peso",
    SupportedCurrencies.UZS: "Uzbekistan Som",
    SupportedCurrencies.VES: "Venezuelan Bolívar Soberano",
    SupportedCurrencies.VND: "Vietnamese Dong",
    SupportedCurrencies.VUV: "Vanuatu Vatu",
    SupportedCurrencies.WST: "Samoan Tala",
    SupportedCurrencies.XAF: "CFA Franc BEAC",
    SupportedCurrencies.XCD: "East Caribbean Dollar",
    SupportedCurrencies.XOF: "CFA Franc BCEAO",
    SupportedCurrencies.XPF: "CFP Franc",
    SupportedCurrencies.YER: "Yemeni Rial",
    SupportedCurrencies.ZAR: "South African Rand",
    SupportedCurrencies.ZMW: "Zambian Kwacha",
}

SUPPORTED_CURRENCY_CODES: set[SupportedCurrencies] = set(SUPPORTED_CURRENCIES.keys())
SUPPORTED_CURRENCY_NAMES: set[str] = set(SUPPORTED_CURRENCIES.values())
