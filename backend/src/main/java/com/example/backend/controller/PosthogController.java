package com.example.backend.controller;

import com.example.backend.model.ApiHeatmapGetDTO;
import com.example.backend.model.HeatmapResponse;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Controller;

import com.example.backend.services.*;
import org.springframework.web.bind.annotation.CrossOrigin;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * posthogController
 */
@Controller
@RequestMapping("/api/heatmap/")
public class PosthogController {

    @Autowired
    private EventsService eventsService;

    @CrossOrigin(origins = "http://localhost:4200")
    @GetMapping(params = "type=rightclick")
    public ResponseEntity<HeatmapResponse> getRightClickHeatmap(
            @RequestParam(name = "type") String type,
            @RequestParam(name = "date_from", defaultValue = "7d") String date,
            @RequestParam(name = "url_exact", required = false) String urlExact,
            @RequestParam(name = "aggregation") String aggregation) {
        List<ApiHeatmapGetDTO> results;
        results = eventsService.getRightClickHeatmap(type, date, urlExact, aggregation);
        return new ResponseEntity<>(new HeatmapResponse(results), HttpStatus.OK);
    }

    @CrossOrigin(origins = "http://localhost:4200")
    @GetMapping(params = "type")
    public ResponseEntity<HeatmapResponse> getAllHeatmap(
            @RequestParam(name = "type") String type,
            @RequestParam(name = "date_from", defaultValue = "7d") String date,
            @RequestParam(name = "url_exact", required = false) String urlExact,
            @RequestParam(name = "aggregation") String aggregation) {
        List<ApiHeatmapGetDTO> results;
        results = eventsService.getAllHeatmap(type, date, urlExact, aggregation);
        return new ResponseEntity<>(new HeatmapResponse(results), HttpStatus.OK);
    }
}
