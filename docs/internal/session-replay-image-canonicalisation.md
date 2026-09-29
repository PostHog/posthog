# Session replay image canonicalisation

The replay mirror collects remote image URLs. The shared Rust URL policy defines the fetch URL and the global image identity.

## Source selection

For an `img` with a usable `srcset`, the collector selects a candidate within a size limit and ignores `src` and `rr_src`. The ignored attributes become placeholders and produce no image refs. This rule applies to every site and both replay walkers.

For width descriptors, the collector chooses the largest candidate at or below 1024w. For density descriptors, it chooses the largest candidate at or below 2x. If all candidates exceed the relevant limit, it chooses the smallest. The first candidate wins a tie. The same rule applies to `picture` source elements. CSS `image-set()` retains its existing largest-density selection.

These limits guide source selection; they do not enforce a download-size or total-pixel limit. Width descriptors omit height, and density descriptors omit absolute dimensions. The choice never rewrites a URL or changes its aspect ratio. The fetcher and scrubber still enforce their byte and decoded-pixel limits. The selection limit is separate from the scrubber's output ceiling because detection requires more detail than storage.

A usable candidate is an admitted HTTPS image URL or a supported base64 image data URI. Trusted re-scrubbing also recognises an existing image ref. If `srcset` is empty, malformed, mixes widths and densities, or selects a refused URL, the collector retains the `src` and `rr_src` fallbacks. The collector does not infer relationships between separate `picture` children or between separate attribute mutations.

## Shopify resizing

The policy recognises raster images on `cdn.shopify.com/s/files/<numeric store path>/{files,products,collections}/` and `/cdn/shop/{files,products,collections}/` on a single-label `*.myshopify.com` storefront. Custom domains keep their resize values because the path alone does not prove Shopify semantics. It keeps the hostname, store path, asset name, file extension, version, and other retained query bytes distinct.

Recognised resizes use a consistent size in the dedup URL, which determines the global identity. The fetch URL retains its observed resize suffix and query bytes:

- A `width` query without `height` becomes `width=1024`.
- A `height` query without `width` becomes `height=1024`.
- Uncropped legacy suffixes such as `_480x`, `_x480`, and `_480x480` use an integer scale with a longest requested side at most 1024. Two dimensions retain their exact requested ratio. Ratios that cannot fit at that size remain unchanged.
- Legacy sizes `pico`, `icon`, `thumb`, `small`, `compact`, `medium`, `large`, and `grande` use a 1024-by-1024 bounding box.
- A legacy `@2x` or `@3x` density suffix is absorbed into the consistent dedup size.

The dedup URL is an identity input, not a fetch target. For example, `photo_480x.jpg` has a dedup suffix of `photo_1024x.jpg`, but the fetcher still requests `photo_480x.jpg`. Within a collection batch, the first observed variant supplies the fetch URL. Across batches, the first successfully stored variant can supply the image for later variants, including larger ones.

Crop suffixes, crop parameters, and query URLs with both `width` and `height` remain unchanged. The crop result can depend on the original image bounds as well as the requested ratio. Unknown query fields, duplicate resize fields, invalid dimensions, and combined legacy/query resizing also keep their original resize values. `_480px` is not a recognised Shopify suffix.

The normalised identity size does not set the fetch or output resolution. The URL-image scrubber defaults to a 50,000-pixel output ceiling and can store less to satisfy its detection constraints. Scrubbing still applies to every fetched image.

See Shopify's [image_url](https://shopify.dev/docs/api/liquid/filters/image_url) and [legacy img_url](https://shopify.dev/docs/api/liquid/filters/img_url) contracts.

## Global query rules

Outside recognised Shopify image routes, `width`, `height`, `w`, `h`, and `size` remain part of the global identity. Their names do not establish whether they select a resize, crop, generated image, or another resource. Downsampling does not make different crops equivalent.

The existing volatile-query rules still apply. Admission checks run before size normalisation, so a signed URL is refused rather than rewritten into an unsigned request. Unrelated query fields retain their original order and encoding.

## Rollout

The mirror and image fetcher use the same compiled Rust policy. Deploy both to obtain consistent identity rules. Existing queued jobs keep their original refs and observed resize values. Existing stored refs remain readable, while newly collected size variants use their new shared identity.
