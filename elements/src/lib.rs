//! Python extension to deserialize chains of HTML elements as serialized by PostHog
use std::collections;

use once_cell::sync::Lazy;
use pyo3::prelude::*;
use pyo3::types::{IntoPyDict, PyDict, PyList};
use rayon::prelude::*;
use regex::{Regex, RegexBuilder};

static SPLIT_CHAIN_REGEX: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?:[^\s;"]|"(?:\\.|[^"])*")+"#)
        .expect("hard-coded regular expression to be valid")
});
static SPLIT_CLASS_ATTRIBUTES: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(.*?)($|:([a-zA-Z\-\_0-9]*=.*))"#)
        .expect("hard-coded regular expression to be valid")
});
static PARSE_ATTRIBUTES_REGEX: Lazy<Regex> = Lazy::new(|| {
    RegexBuilder::new(r#"(?P<attribute>(?P<key>.*?)\=\"(?P<value>.*?[^\\])\")"#)
        .multi_line(true)
        .build()
        .expect("hard-coded regular expression should be valid")
});

/// Represents an HTML element.
///
/// Meant to replicate a PostHog `Element` model internally.
struct Element {
    order: usize,
    text: Option<String>,
    tag_name: Option<String>,
    href: Option<String>,
    attr_id: Option<String>,
    attr_class: Vec<String>,
    nth_child: Option<u64>,
    nth_of_type: Option<u64>,
    attributes: collections::HashMap<String, String>,
}

impl Element {
    fn new_with_order(order: usize) -> Self {
        Self {
            order,
            text: None,
            tag_name: None,
            href: None,
            attr_id: None,
            attr_class: Vec::new(),
            nth_child: None,
            nth_of_type: None,
            attributes: collections::HashMap::new(),
        }
    }

    fn with_text(&mut self, text: &str) {
        self.text = Some(text.to_owned());
    }

    fn with_tag_name(&mut self, tag_name: &str) {
        self.tag_name = Some(tag_name.to_owned());
    }

    fn with_href(&mut self, href: &str) {
        self.href = Some(href.to_owned());
    }

    fn with_attr_id(&mut self, attr_id: &str) {
        self.attr_id = Some(attr_id.to_owned());
    }

    fn extend_attr_class<'a>(&mut self, attr_class: &str) {
        self.attr_class
            .extend(attr_class.split(".").filter_map(|cl| {
                if cl != "" {
                    Some(cl.to_string())
                } else {
                    None
                }
            }));
    }

    fn with_nth_child(&mut self, nth_child: u64) {
        self.nth_child = Some(nth_child);
    }

    fn with_nth_of_type(&mut self, nth_of_type: u64) {
        self.nth_of_type = Some(nth_of_type);
    }

    fn with_attribute(&mut self, key: &str, value: &str) {
        self.attributes.insert(key.to_owned(), value.to_owned());
    }
}

impl IntoPy<PyObject> for Element {
    /// Convert a Rust `Element` into a Python dictionary.
    fn into_py(self, py: Python<'_>) -> PyObject {
        let dict = &[("order", self.order)].into_py_dict_bound(py);

        if let Some(href) = self.href {
            dict.set_item("href", href);
        }

        if let Some(nth_child) = self.nth_child {
            dict.set_item("nth_child", nth_child);
        }

        if let Some(nth_of_type) = self.nth_of_type {
            dict.set_item("nth_of_type", nth_of_type);
        }

        if let Some(text) = self.text {
            dict.set_item("text", text);
        }

        if let Some(attr_id) = self.attr_id {
            dict.set_item("attr_id", attr_id);
        }

        if let Some(tag_name) = self.tag_name {
            dict.set_item("tag_name", tag_name);
        }

        if self.attr_class.len() > 0 {
            dict.set_item("attr_class", self.attr_class);
        } else {
            dict.set_item("attr_class", py.None());
        }

        dict.set_item("attributes", self.attributes);

        dict.into_py(py)
    }
}

/// Deserialize a chain of HTML elements into a Python dictionary
///
/// This function mimics the `chain_to_elements` Python function provided
/// by the `posthog.models.element.elements` module. The only difference is
/// that this function returns a dictionary instead of a Django model.
#[pyfunction]
pub fn chain_to_elements_dict(chain: &str) -> PyResult<PyObject> {
    let elements: Vec<Element> = SPLIT_CHAIN_REGEX
        .find_iter(chain)
        .collect::<Vec<regex::Match<'_>>>()
        .into_par_iter()
        .enumerate()
        .map(|(index, el_string): (usize, regex::Match<'_>)| -> Element {
            let mut element = Element::new_with_order(index);

            if let Some(el_string_split) = SPLIT_CLASS_ATTRIBUTES.captures(el_string.as_str()) {
                if let Some(captured) = el_string_split.get(0) {
                    if let Some(splitted) = captured.as_str().split_once(".") {
                        element.with_tag_name(splitted.0);
                        element.extend_attr_class(splitted.1);
                    } else {
                        element.with_tag_name(captured.as_str());
                    }
                }

                if let Some(captured) = el_string_split.get(2) {
                    for (_, [_, key, value]) in PARSE_ATTRIBUTES_REGEX
                        .captures_iter(captured.as_str())
                        .map(|c| c.extract())
                    {
                        match key {
                            "href" => element.with_href(value),
                            "text" => element.with_text(value),
                            "attr_id" => element.with_attr_id(value),
                            "nth-child" => {
                                let nth_child = value.parse::<u64>().unwrap();
                                element.with_nth_child(nth_child)
                            }
                            "nth-of-type" => {
                                let nth_of_type = value.parse::<u64>().unwrap();
                                element.with_nth_of_type(nth_of_type)
                            }
                            k => element.with_attribute(k, value),
                        };
                    }
                    element
                } else {
                    element
                }
            } else {
                element
            }
        })
        .collect();

    Python::with_gil(|py| Ok(elements.into_py(py)))
}

#[pymodule]
fn elements(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(chain_to_elements_dict, m)?)?;
    Ok(())
}
