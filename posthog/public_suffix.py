import tldextract

# Uses the Public Suffix List snapshot bundled with tldextract. The default extractor (`tldextract.extract`)
# fetches the live list with no timeout, so a stalled connection blocks the caller until the worker dies.
extract_domain_parts = tldextract.TLDExtract(suffix_list_urls=())
