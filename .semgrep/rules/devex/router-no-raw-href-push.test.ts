// @ts-nocheck
// Test fixture for the router-no-raw-href-push rule.

// ruleid: router-no-raw-href-push
router.actions.push(item.href)

// ruleid: router-no-raw-href-push
router.actions.replace(item.href)

// ruleid: router-no-raw-href-push
router.actions.push(product.href)

// ruleid: router-no-raw-href-push
router.actions.push(notification.record.href)

// ruleid: router-no-raw-href-push
router.actions.push(item.href, searchParams)

// A path built from `urls.*` is same-origin by construction, so it stays allowed.
// ok: router-no-raw-href-push
router.actions.push(urls.insightView(insight.short_id))

// ok: router-no-raw-href-push
router.actions.push('/project/1/dashboard')

// ok: router-no-raw-href-push
router.actions.push(urls.ai(undefined, searchValue.trim()))

// ok: router-no-raw-href-push
navigateToHref(item.href)

// ok: router-no-raw-href-push
newInternalTab(item.href)
