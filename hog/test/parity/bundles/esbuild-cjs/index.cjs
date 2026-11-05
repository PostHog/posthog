var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __esm = (fn, res, err) => function __init() {
  if (err) throw err[0];
  try {
    return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
  } catch (e) {
    throw err = [e], e;
  }
};
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/reviews.js
var reviews_exports = {};
__export(reviews_exports, {
  fetchReviews: () => fetchReviews
});
function fetchReviews(productId) {
  if (!productId) {
    throw new Error("Missing product");
  }
  return [{ productId, stars: 5, text: "Works as described" }];
}
var init_reviews = __esm({
  "src/reviews.js"() {
  }
});

// src/index.js
var index_exports = {};
__export(index_exports, {
  checkout: () => checkout,
  loadReviews: () => loadReviews
});
module.exports = __toCommonJS(index_exports);

// src/cart.js
function formatPrice(cents) {
  return `$${(cents / 100).toFixed(2)}`;
}
function parseQuantity(value) {
  const parsed = Number.parseInt(value, 10);
  if (Number.isNaN(parsed)) {
    throw new TypeError(`Invalid quantity: ${value}`);
  }
  return parsed;
}

// src/ui/badge.js
function renderBadge(label) {
  const badge = { kind: "badge", label, createdAt: "\xE9\u65E5\u{1F600}" };
  return JSON.stringify(badge);
}

// src/index.js
function checkout(items) {
  let total = 0;
  for (const item of items) {
    total += item.price * parseQuantity(item.quantity);
  }
  if (total <= 0) {
    throw new Error("Cart total must be positive");
  }
  return renderBadge(`Total: ${formatPrice(total)}`);
}
async function loadReviews() {
  const { fetchReviews: fetchReviews2 } = await Promise.resolve().then(() => (init_reviews(), reviews_exports));
  return fetchReviews2("example-product");
}
